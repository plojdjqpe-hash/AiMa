"""Detector unit tests — no network access."""

from __future__ import annotations

from datetime import timedelta

from aima.detector import detect_incidents
from aima.types import BlockType, IncidentSeverity, ProbeReport, utcnow


def _ok(profile: str, vantage: str, *, minutes_ago: int = 0) -> ProbeReport:
    return ProbeReport(
        profile_id=profile,
        vantage=vantage,
        started_at=utcnow() - timedelta(minutes=minutes_ago),
        duration_ms=30.0,
        success=True,
        block_type=BlockType.NONE,
        rtt_ms=30.0,
    )


def _fail(
    profile: str,
    vantage: str,
    block_type: BlockType,
    *,
    minutes_ago: int = 0,
) -> ProbeReport:
    return ProbeReport(
        profile_id=profile,
        vantage=vantage,
        started_at=utcnow() - timedelta(minutes=minutes_ago),
        duration_ms=1500.0,
        success=False,
        block_type=block_type,
        error="synthetic",
    )


def test_no_reports_no_incidents() -> None:
    assert detect_incidents([]) == []


def test_low_failure_rate_does_not_trigger() -> None:
    reports = [_ok("p", "v", minutes_ago=i) for i in range(20)]
    reports += [_fail("p", "v", BlockType.SNI_BLOCK, minutes_ago=i) for i in range(2)]
    incidents = detect_incidents(reports)
    assert incidents == []


def test_sni_block_majority_emits_incident() -> None:
    reports = [
        _fail("reality-cf", "MTS", BlockType.SNI_BLOCK, minutes_ago=i) for i in range(15)
    ] + [_ok("reality-cf", "MTS", minutes_ago=i) for i in range(2)]
    incidents = detect_incidents(reports)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.profile_id == "reality-cf"
    assert inc.vantage == "MTS"
    assert inc.block_type is BlockType.SNI_BLOCK
    assert inc.severity in (IncidentSeverity.HIGH, IncidentSeverity.CRITICAL)
    assert inc.suggested_recipes  # non-empty


def test_quic_drop_classified_correctly() -> None:
    reports = [
        _fail("hys", "BL", BlockType.QUIC_DROP, minutes_ago=i) for i in range(12)
    ]
    incidents = detect_incidents(reports)
    assert any(i.block_type is BlockType.QUIC_DROP for i in incidents)
    qd = next(i for i in incidents if i.block_type is BlockType.QUIC_DROP)
    assert "force_tcp_only" in qd.suggested_recipes


def test_min_samples_threshold() -> None:
    # 4 failures should NOT trigger when min_samples=5.
    reports = [_fail("p", "v", BlockType.SNI_BLOCK, minutes_ago=i) for i in range(4)]
    assert detect_incidents(reports, min_samples=5) == []


def test_incident_ids_stable() -> None:
    reports = [_fail("p", "v", BlockType.SNI_BLOCK, minutes_ago=i) for i in range(10)]
    a = detect_incidents(reports)
    b = detect_incidents(reports)
    assert a[0].id == b[0].id


def test_throttle_detection() -> None:
    # Fast handshakes early, RTT explodes at the end → throttle.
    reports = [
        ProbeReport(
            profile_id="p",
            vantage="Yota",
            started_at=utcnow() - timedelta(minutes=20 - i),
            duration_ms=30.0,
            success=True,
            block_type=BlockType.NONE,
            rtt_ms=80.0,
        )
        for i in range(15)
    ] + [
        ProbeReport(
            profile_id="p",
            vantage="Yota",
            started_at=utcnow() - timedelta(minutes=5 - i),
            duration_ms=2000.0,
            success=True,
            block_type=BlockType.NONE,
            rtt_ms=2000.0,
        )
        for i in range(5)
    ]
    incidents = detect_incidents(reports)
    assert any(i.block_type is BlockType.THROTTLE for i in incidents)
