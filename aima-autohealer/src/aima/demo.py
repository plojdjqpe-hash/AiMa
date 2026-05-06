"""Synthetic dataset that demonstrates how the detector reacts to common DPI patterns.

We pre-seed a `Store` with realistic-looking probe reports across multiple
vantages (RU mobile, RU residential, EU baseline) and a few RKN-style outages:

  * SNI-block on `www.cloudflare.com` from MTS-mobile only.
  * QUIC/UDP drop on Bilain from minute 10 onward.
  * REALITY late-reset on the Cloudflare REALITY profile only on Megafon.
  * Throttle on Yota.
"""

from __future__ import annotations

import random
from datetime import timedelta

from .probe import Vantage
from .store import Store
from .types import (
    BlockType,
    ProbeProfile,
    ProbeReport,
    TransportKind,
    utcnow,
)

random.seed(1337)


VANTAGES = [
    Vantage(name="MTS-mobile-MSK", asn=8359, provider="MTS", region="Москва"),
    Vantage(name="Beeline-mobile-SPB", asn=3216, provider="Beeline", region="СПб"),
    Vantage(name="Megafon-home-EKB", asn=31133, provider="Megafon", region="Екб"),
    Vantage(name="Yota-mobile-NSK", asn=25159, provider="Yota", region="Нвск"),
    Vantage(name="DO-FRA1-baseline", asn=14061, provider="DigitalOcean", region="EU"),
]

PROFILES = [
    ProbeProfile(
        id="reality-cloudflare",
        label="VLESS+REALITY @ www.cloudflare.com",
        kind=TransportKind.VLESS_REALITY,
        host="89.125.85.198",
        port=8443,
        sni="www.cloudflare.com",
    ),
    ProbeProfile(
        id="reality-apple",
        label="VLESS+REALITY @ www.apple.com",
        kind=TransportKind.VLESS_REALITY,
        host="89.125.85.198",
        port=8443,
        sni="www.apple.com",
    ),
    ProbeProfile(
        id="hysteria2-quic",
        label="Hysteria2 UDP/443",
        kind=TransportKind.HYSTERIA2,
        host="89.125.85.198",
        port=443,
    ),
    ProbeProfile(
        id="dns-cf",
        label="DNS lookup cloudflare.com",
        kind=TransportKind.DNS,
        host="www.cloudflare.com",
    ),
]


def _gen_report(
    profile: ProbeProfile,
    vantage: Vantage,
    *,
    minute: int,
    block_type: BlockType,
    base_rtt_ms: float,
    success: bool,
) -> ProbeReport:
    started = utcnow() - timedelta(minutes=45 - minute)
    jitter = random.uniform(-15, 15)
    return ProbeReport(
        profile_id=profile.id,
        vantage=vantage.name,
        asn=vantage.asn,
        provider=vantage.provider,
        region=vantage.region,
        started_at=started,
        duration_ms=base_rtt_ms + jitter + (0 if success else 1500),
        success=success,
        block_type=block_type,
        rtt_ms=base_rtt_ms + jitter if success else None,
        handshake_ms=(base_rtt_ms * 1.5 + jitter) if success else None,
        error=None if success else f"synthetic {block_type.value}",
    )


def seed_demo(store: Store, *, minutes: int = 45) -> None:
    for p in PROFILES:
        store.upsert_profile(p)

    for minute in range(minutes):
        for vantage in VANTAGES:
            for profile in PROFILES:
                base_rtt = {
                    "MTS-mobile-MSK": 38.0,
                    "Beeline-mobile-SPB": 42.0,
                    "Megafon-home-EKB": 65.0,
                    "Yota-mobile-NSK": 95.0,
                    "DO-FRA1-baseline": 12.0,
                }[vantage.name]

                # Pattern 1: SNI block on Cloudflare-REALITY from MTS, starting minute 5.
                if (
                    vantage.name == "MTS-mobile-MSK"
                    and profile.id == "reality-cloudflare"
                    and minute >= 5
                ):
                    success = random.random() < 0.05
                    bt = BlockType.NONE if success else BlockType.SNI_BLOCK
                # Pattern 2: QUIC drop on Beeline starting minute 10.
                elif (
                    vantage.name == "Beeline-mobile-SPB"
                    and profile.id == "hysteria2-quic"
                    and minute >= 10
                ):
                    success = False
                    bt = BlockType.QUIC_DROP
                # Pattern 3: REALITY late-reset on Megafon for Cloudflare REALITY.
                elif (
                    vantage.name == "Megafon-home-EKB"
                    and profile.id == "reality-cloudflare"
                    and minute >= 15
                ):
                    success = random.random() < 0.15
                    bt = BlockType.NONE if success else BlockType.REALITY_DETECT
                # Pattern 4: Throttle on Yota — handshake ok but RTT explodes after minute 20.
                elif vantage.name == "Yota-mobile-NSK" and minute >= 20:
                    base_rtt = base_rtt * (1 + (minute - 20) / 5)
                    success = True
                    bt = BlockType.NONE
                else:
                    success = random.random() < 0.97
                    bt = BlockType.NONE if success else BlockType.TCP_RST

                store.insert_report(
                    _gen_report(
                        profile,
                        vantage,
                        minute=minute,
                        block_type=bt,
                        base_rtt_ms=base_rtt,
                        success=success,
                    )
                )
