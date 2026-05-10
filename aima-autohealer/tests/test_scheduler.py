"""Slow-loop passive learning behaviour."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aima.probe import Vantage
from aima.scheduler import HealerScheduler
from aima.store import Store
from aima.types import BlockType, ProbeProfile, ProbeReport, TransportKind


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "sched.db")


@pytest.fixture
def vantage() -> Vantage:
    return Vantage(name="MTS-mobile-MSK", asn=8359, provider="MTS", region="MSK")


def _seed_failing_profile(store: Store, *, asn: int = 8359) -> None:
    profile = ProbeProfile(
        id="cf-reality",
        label="CF REALITY",
        kind=TransportKind.DIRECT_TLS,
        host="www.cloudflare.com",
        port=443,
        sni="www.cloudflare.com",
    )
    store.upsert_profile(profile)

    base = datetime.now(UTC) - timedelta(minutes=15)
    # 30 reports, 90% failing with SNI_BLOCK -> easy detection
    for i in range(30):
        success = i < 3
        store.insert_report(
            ProbeReport(
                profile_id=profile.id,
                vantage="MTS-mobile-MSK",
                asn=asn,
                started_at=base + timedelta(seconds=20 * i),
                duration_ms=200.0,
                success=success,
                block_type=BlockType.NONE if success else BlockType.SNI_BLOCK,
                error=None if success else "tls reset",
            )
        )


def test_slow_loop_records_observations_for_suggested_recipes(
    store: Store, vantage: Vantage
) -> None:
    _seed_failing_profile(store)

    sched = HealerScheduler(store, vantage, fast_interval_minutes=5, slow_interval_minutes=60)
    asyncio.run(sched.slow_loop())

    cur = store._conn.cursor()  # noqa: SLF001
    rows = cur.execute(
        "SELECT recipe_id, success_count, failure_count, observed_count "
        "FROM learned_rules WHERE asn=? AND block_type=?",
        (vantage.asn, BlockType.SNI_BLOCK.value),
    ).fetchall()
    cur.close()

    assert rows, "expected at least one observation row recorded"
    by_recipe = {r["recipe_id"]: r for r in rows}
    # The detector's catalogue suggests rotate_sni_pool for SNI blocks;
    # exact recipe set may evolve so check at least one shows up with
    # observed_count >= 1 and zero outcomes.
    for r in rows:
        assert r["success_count"] == 0
        assert r["failure_count"] == 0
        assert r["observed_count"] >= 1
    assert "rotate_sni_pool" in by_recipe


def test_slow_loop_handles_empty_store_gracefully(
    store: Store, vantage: Vantage
) -> None:
    sched = HealerScheduler(store, vantage)
    asyncio.run(sched.slow_loop())  # must not raise


def test_asn_lookup_falls_back_to_none_for_unknown_vantage(
    store: Store, vantage: Vantage
) -> None:
    sched = HealerScheduler(store, vantage)
    assert sched._asn_for_vantage("MTS-mobile-MSK") == vantage.asn  # noqa: SLF001
    assert sched._asn_for_vantage("Beeline-mobile-SPB") is None  # noqa: SLF001
    assert sched._asn_for_vantage(None) is None  # noqa: SLF001
