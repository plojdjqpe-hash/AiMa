"""Pydantic models shared across probe → detector → store → API."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class BlockType(StrEnum):
    """Classified outcome of a single probe attempt."""

    NONE = "none"  # connection succeeded end-to-end
    DNS_BLOCK = "dns_block"  # NXDOMAIN / poisoned record
    TCP_TIMEOUT = "tcp_timeout"  # SYN-ACK never arrived
    TCP_RST = "tcp_rst"  # connection reset before TLS started
    SNI_BLOCK = "sni_block"  # TLS reset right after ClientHello (SNI-based)
    REALITY_DETECT = "reality_detect"  # TLS handshake completed but app data RST/timeout shortly after
    QUIC_DROP = "quic_drop"  # UDP/443 100% loss but TCP/443 ok
    HTTP_TAMPER = "http_tamper"  # response body rewritten (RKN block page / TLS interception)
    THROTTLE = "throttle"  # throughput collapses after a few seconds
    UNKNOWN = "unknown"


class TransportKind(StrEnum):
    """High level transport family for a probed profile."""

    DIRECT_TCP = "direct_tcp"  # plain TCP probe to a host:port
    DIRECT_TLS = "direct_tls"  # TLS handshake with custom SNI
    DIRECT_HTTPS = "direct_https"  # HTTPS GET baseline
    DNS = "dns"  # DNS resolution baseline
    VLESS_REALITY = "vless_reality"  # full VLESS+REALITY proxy probe (requires sing-box, optional)
    HYSTERIA2 = "hysteria2"  # QUIC-based, optional
    UDP_QUIC = "udp_quic"  # raw UDP/443 reachability check


class ProbeProfile(BaseModel):
    """A single thing we want to probe (e.g. one inbound, one SNI, one QUIC endpoint)."""

    id: str
    label: str
    kind: TransportKind
    host: str
    port: int = 443
    sni: str | None = None
    expected_status: int | None = 200
    timeout_seconds: float = 6.0
    # extra config for transports that need it (sing-box JSON, etc.)
    extra: dict = Field(default_factory=dict)


class ProbeReport(BaseModel):
    """Result of probing a profile from a specific vantage point."""

    profile_id: str
    vantage: str  # vantage-point identifier: "MTS-mobile-MSK", "DO-FRA1-baseline", etc.
    asn: int | None = None
    provider: str | None = None
    region: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    duration_ms: float
    success: bool
    block_type: BlockType
    rtt_ms: float | None = None
    handshake_ms: float | None = None
    throughput_kbps: float | None = None
    error: str | None = None
    raw: dict = Field(default_factory=dict)  # raw socket/TLS/HTTP details for debugging


class IncidentSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Incident(BaseModel):
    """A classified outage detected by the rule/statistical engine."""

    id: str
    profile_id: str | None  # may be None when incident applies to a vantage globally
    vantage: str | None
    block_type: BlockType
    severity: IncidentSeverity
    confidence: float  # 0..1
    started_at: datetime
    last_seen_at: datetime
    sample_count: int
    failure_rate: float
    summary: str
    suggested_recipes: list[str] = Field(default_factory=list)
