"""End-to-end test: seed_demo() should produce detectable incidents matching the script."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from aima.demo import seed_demo
from aima.detector import detect_incidents
from aima.store import Store
from aima.types import BlockType, utcnow


def test_demo_produces_expected_incident_types(tmp_path: Path) -> None:
    store = Store(tmp_path / "demo.db")
    seed_demo(store, minutes=45)
    reports = store.reports_since(since=utcnow() - timedelta(minutes=60))
    incidents = detect_incidents(reports, window_minutes=60)

    types = {(inc.vantage, inc.block_type) for inc in incidents}

    # SNI block on MTS for Cloudflare REALITY profile.
    assert ("MTS-mobile-MSK", BlockType.SNI_BLOCK) in types
    # QUIC drop on Beeline.
    assert ("Beeline-mobile-SPB", BlockType.QUIC_DROP) in types
    # REALITY late-reset on Megafon.
    assert ("Megafon-home-EKB", BlockType.REALITY_DETECT) in types
    # Throttle on Yota.
    assert any(inc.block_type is BlockType.THROTTLE and inc.vantage == "Yota-mobile-NSK" for inc in incidents)

    # Baseline DO should not produce any incidents.
    do_incidents = [inc for inc in incidents if inc.vantage == "DO-FRA1-baseline"]
    assert do_incidents == []
