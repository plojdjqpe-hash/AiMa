"""Incident detector.

Runs over the latest window of `ProbeReport`s and produces `Incident`s when
failure rates spike or a specific block_type concentrates on a profile/vantage.

The classifier is intentionally simple and explainable. The LLM-driven layer
(future module `llm_decision.py`) will be invoked only when this engine can't
reach a confident verdict or its catalog of fixes has been exhausted.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from .types import (
    BlockType,
    Incident,
    IncidentSeverity,
    ProbeReport,
    utcnow,
)

# Recipe identifiers that the (future) mutation engine knows how to apply.
RECIPE_BY_BLOCK: dict[BlockType, list[str]] = {
    BlockType.SNI_BLOCK: [
        "rotate_sni_pool",
        "switch_to_xhttp_path",
        "fallback_cdn_ws",
    ],
    BlockType.TCP_RST: [
        "activate_backup_inbound",
        "add_ipv6",
        "switch_to_warp_relay",
    ],
    BlockType.TCP_TIMEOUT: [
        "activate_backup_inbound",
        "switch_to_alt_port_8443_2053",
        "switch_to_warp_relay",
    ],
    BlockType.REALITY_DETECT: [
        "rotate_pubkey",
        "change_dest_sni",
        "regenerate_short_ids",
    ],
    BlockType.QUIC_DROP: [
        "disable_udp_outbounds",
        "force_tcp_only",
    ],
    BlockType.DNS_BLOCK: [
        "switch_doh_endpoint",
        "force_doh_cloudflare",
        "force_doh_quad9",
    ],
    BlockType.HTTP_TAMPER: [
        "fallback_cdn_ws",
        "enable_padding",
    ],
    BlockType.THROTTLE: [
        "enable_padding",
        "switch_to_hysteria2",
        "multipath_outbounds",
    ],
}


def _severity_for(failure_rate: float) -> IncidentSeverity:
    if failure_rate >= 0.95:
        return IncidentSeverity.CRITICAL
    if failure_rate >= 0.75:
        return IncidentSeverity.HIGH
    if failure_rate >= 0.5:
        return IncidentSeverity.MEDIUM
    if failure_rate >= 0.25:
        return IncidentSeverity.LOW
    return IncidentSeverity.INFO


def _incident_id(*parts: str) -> str:
    """Stable id so re-evaluation of the same incident updates it instead of duplicating."""

    return hashlib.sha1(("|".join(parts)).encode()).hexdigest()[:16]


def detect_throttle(reports: list[ProbeReport]) -> bool:
    """Heuristic throttle detection: handshake fine but RTT explodes over time.

    We compare the median RTT in the *first quarter* of the observation window
    against the median in the *last quarter*. A 3x increase with at least 50ms
    baseline is reported as a throttling event — a pattern characteristic of
    QoS-style traffic shaping rather than outright blocking.
    """

    rtts = sorted(
        ((r.started_at, r.rtt_ms) for r in reports if r.rtt_ms is not None and r.success),
        key=lambda x: x[0],
    )
    if len(rtts) < 8:
        return False
    quarter = max(2, len(rtts) // 4)
    first = [v for _, v in rtts[:quarter]]
    last = [v for _, v in rtts[-quarter:]]
    first_med = statistics.median(first)
    last_med = statistics.median(last)
    return last_med > first_med * 3 and first_med > 50


def _summarize(
    *,
    block_type: BlockType,
    profile_id: str | None,
    vantage: str | None,
    failure_rate: float,
    sample_count: int,
) -> str:
    where = []
    if profile_id is not None:
        where.append(f"profile={profile_id}")
    if vantage is not None:
        where.append(f"vantage={vantage}")
    loc = ", ".join(where) or "global"
    return (
        f"{block_type.value} detected ({failure_rate:.0%} failure on {sample_count} samples, {loc})"
    )


def detect_incidents(
    reports: list[ProbeReport],
    *,
    window_minutes: int = 30,
    min_samples: int = 5,
    failure_threshold: float = 0.4,
) -> list[Incident]:
    """Group reports by (profile, vantage), classify dominant block_type, emit incidents."""

    if not reports:
        return []
    now = utcnow()
    cutoff = now - timedelta(minutes=window_minutes)
    fresh = [r for r in reports if r.started_at >= cutoff]
    if not fresh:
        return []

    grouped: dict[tuple[str, str], list[ProbeReport]] = defaultdict(list)
    for r in fresh:
        grouped[(r.profile_id, r.vantage)].append(r)

    incidents: list[Incident] = []
    for (profile_id, vantage), group in grouped.items():
        sample_count = len(group)
        if sample_count < min_samples:
            continue
        failures = [r for r in group if not r.success]
        failure_rate = len(failures) / sample_count
        # Throttle check first — successful TLS but degraded throughput.
        if detect_throttle(group):
            block_type = BlockType.THROTTLE
            failure_rate = max(failure_rate, 0.5)
        elif failure_rate < failure_threshold:
            continue
        else:
            type_counts = Counter(r.block_type for r in failures)
            block_type, _ = type_counts.most_common(1)[0]
            if block_type is BlockType.NONE or block_type is BlockType.UNKNOWN:
                # demote to a generic TCP_RST hint so downstream still has recipes
                block_type = BlockType.TCP_RST

        # Confidence = dominant-type share of failures, clipped, smoothed by sample size.
        type_share = (
            Counter(r.block_type for r in failures).get(block_type, len(failures))
            / max(1, len(failures))
        )
        size_factor = 1.0 - math.exp(-sample_count / 20.0)  # asymptotically → 1
        confidence = max(0.05, min(0.99, type_share * size_factor))

        incidents.append(
            Incident(
                id=_incident_id(profile_id, vantage, block_type.value),
                profile_id=profile_id,
                vantage=vantage,
                block_type=block_type,
                severity=_severity_for(failure_rate),
                confidence=confidence,
                started_at=min(r.started_at for r in group),
                last_seen_at=max(r.started_at for r in group),
                sample_count=sample_count,
                failure_rate=failure_rate,
                summary=_summarize(
                    block_type=block_type,
                    profile_id=profile_id,
                    vantage=vantage,
                    failure_rate=failure_rate,
                    sample_count=sample_count,
                ),
                suggested_recipes=RECIPE_BY_BLOCK.get(block_type, []),
            )
        )
    return incidents
