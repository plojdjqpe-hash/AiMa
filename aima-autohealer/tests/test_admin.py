"""Tests for the AIMA admin / dashboard endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aima.admin import build_admin_router
from aima.store import Store
from aima.types import (
    BlockType,
    Incident,
    IncidentSeverity,
    ProbeProfile,
    ProbeReport,
    TransportKind,
)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "admin.db")


@pytest.fixture
def app(store: Store) -> FastAPI:
    a = FastAPI()
    a.include_router(build_admin_router(lambda: store), prefix="/aima/admin")
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _seed_basic(store: Store) -> None:
    """Seed enough state that every admin endpoint has something to chew on."""

    profile = ProbeProfile(
        id="cf-reality",
        label="Cloudflare REALITY",
        kind=TransportKind.DIRECT_TLS,
        host="www.cloudflare.com",
        port=443,
        sni="www.cloudflare.com",
    )
    store.upsert_profile(profile)

    now = datetime.now(UTC)
    # 8 successful + 2 failing reports -> 80% success rate, all in the last 24h.
    for i in range(8):
        store.insert_report(
            ProbeReport(
                profile_id=profile.id,
                vantage="MTS-mobile-MSK",
                asn=8359,
                started_at=now - timedelta(minutes=10 + i),
                duration_ms=120.0,
                success=True,
                block_type=BlockType.NONE,
                rtt_ms=12.0,
                handshake_ms=30.0,
                throughput_kbps=15000.0,
            )
        )
    for i in range(2):
        store.insert_report(
            ProbeReport(
                profile_id=profile.id,
                vantage="MTS-mobile-MSK",
                asn=8359,
                started_at=now - timedelta(minutes=2 + i),
                duration_ms=200.0,
                success=False,
                block_type=BlockType.SNI_BLOCK,
                error="tls reset",
            )
        )

    inc = Incident(
        id="inc-test-1",
        profile_id=profile.id,
        vantage="MTS-mobile-MSK",
        block_type=BlockType.SNI_BLOCK,
        severity=IncidentSeverity.HIGH,
        confidence=0.9,
        started_at=now - timedelta(minutes=5),
        last_seen_at=now,
        sample_count=10,
        failure_rate=0.2,
        summary="SNI block on Cloudflare REALITY",
        suggested_recipes=["rotate_sni_pool", "fallback_cdn_ws"],
    )
    store.upsert_incident(inc)

    # mix of real outcomes + passive observations
    store.record_recipe_outcome(
        asn=8359, block_type=BlockType.SNI_BLOCK, recipe_id="rotate_sni_pool", success=True
    )
    store.record_recipe_outcome(
        asn=8359, block_type=BlockType.SNI_BLOCK, recipe_id="rotate_sni_pool", success=False
    )
    for _ in range(3):
        store.record_observation(
            asn=8359, block_type=BlockType.SNI_BLOCK, recipe_id="fallback_cdn_ws"
        )


def test_stats_endpoint_returns_counters(client: TestClient, store: Store) -> None:
    _seed_basic(store)

    resp = client.get("/aima/admin/stats")
    assert resp.status_code == 200
    body = resp.json()

    assert body["profiles"] == 1
    assert body["reports_total"] == 10
    assert body["reports_24h"] == 10
    assert body["success_rate_24h"] == 0.8
    assert body["incidents_total"] == 1
    assert body["incidents_open_60min"] == 1
    assert body["learning_rows"] >= 2
    assert body["vantages_seen"] == 1
    assert body["asns_seen"] == 1
    assert "now" in body


def test_stats_empty_store_returns_zeros(client: TestClient) -> None:
    resp = client.get("/aima/admin/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["profiles"] == 0
    assert body["reports_total"] == 0
    assert body["incidents_total"] == 0
    assert body["learning_rows"] == 0
    assert body["success_rate_24h"] == 0.0


def test_learning_endpoint_lists_rows_with_observations(
    client: TestClient, store: Store
) -> None:
    _seed_basic(store)

    resp = client.get("/aima/admin/learning")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 2

    by_recipe = {r["recipe_id"]: r for r in body["rows"]}

    real = by_recipe["rotate_sni_pool"]
    assert real["success_count"] == 1
    assert real["failure_count"] == 1
    assert real["total_attempts"] == 2
    assert real["success_rate"] == 0.5
    assert real["asn"] == 8359

    passive = by_recipe["fallback_cdn_ws"]
    assert passive["success_count"] == 0
    assert passive["failure_count"] == 0
    assert passive["observed_count"] == 3
    assert passive["total_attempts"] == 0
    assert passive["success_rate"] == 0.0


def test_learning_min_attempts_filters(client: TestClient, store: Store) -> None:
    _seed_basic(store)

    # min_attempts only applies to real outcomes, so only rotate_sni_pool returns
    resp = client.get("/aima/admin/learning?min_attempts=2")
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["recipe_id"] == "rotate_sni_pool"


def test_learning_progress_blends_signals(client: TestClient, store: Store) -> None:
    _seed_basic(store)

    resp = client.get("/aima/admin/learning/progress")
    assert resp.status_code == 200
    body = resp.json()
    # With only one real outcome row + one observation row this is still very
    # early — but the endpoint must always return a number in 0..100.
    assert 0.0 <= body["percent_complete"] <= 100.0
    assert body["coverage_pairs_seen"] == 1
    assert body["coverage_target"] == 32
    assert "rotate_sni_pool" in body["recipes_with_outcomes"]
    assert "fallback_cdn_ws" in body["recipes_observed"]
    assert body["observation_rows"] >= 1
    assert body["total_rows"] >= 2


def test_learning_progress_empty_store_returns_zero(client: TestClient) -> None:
    resp = client.get("/aima/admin/learning/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["percent_complete"] == 0.0
    assert body["coverage_pairs_seen"] == 0
    assert body["recipes_with_outcomes"] == []
    assert body["recipes_observed"] == []


def test_telemetry_summary_rolls_up_per_profile(
    client: TestClient, store: Store
) -> None:
    _seed_basic(store)

    resp = client.get("/aima/admin/telemetry/summary?hours=24")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_reports"] == 10
    assert body["by_block_type"]["none"] == 8
    assert body["by_block_type"]["sni_block"] == 2
    assert body["by_vantage"]["MTS-mobile-MSK"] == 10
    assert len(body["profiles"]) == 1
    p = body["profiles"][0]
    assert p["profile_id"] == "cf-reality"
    assert p["samples"] == 10
    assert p["successes"] == 8
    assert p["success_rate"] == 0.8
    assert p["block_types"]["none"] == 8
    assert p["block_types"]["sni_block"] == 2
    assert p["avg_rtt_ms"] == 12.0
    assert p["avg_handshake_ms"] == 30.0


def test_telemetry_summary_clamps_hours(client: TestClient, store: Store) -> None:
    _seed_basic(store)

    # Negative or absurdly large hours must not 500
    for h in (-1, 0, 999):
        resp = client.get(f"/aima/admin/telemetry/summary?hours={h}")
        assert resp.status_code == 200
        assert "by_block_type" in resp.json()
