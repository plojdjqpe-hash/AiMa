"""Store roundtrip tests."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from aima.store import Store
from aima.types import (
    BlockType,
    Incident,
    IncidentSeverity,
    ProbeProfile,
    ProbeReport,
    TransportKind,
    utcnow,
)


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def test_profile_roundtrip(store: Store) -> None:
    p = ProbeProfile(
        id="p1",
        label="hello",
        kind=TransportKind.DIRECT_TLS,
        host="example.com",
        sni="example.com",
        extra={"k": "v"},
    )
    store.upsert_profile(p)
    [back] = store.list_profiles()
    assert back == p


def test_report_query_window(store: Store) -> None:
    now = utcnow()
    store.insert_report(
        ProbeReport(
            profile_id="p",
            vantage="v",
            started_at=now - timedelta(minutes=120),
            duration_ms=10.0,
            success=True,
            block_type=BlockType.NONE,
        )
    )
    store.insert_report(
        ProbeReport(
            profile_id="p",
            vantage="v",
            started_at=now - timedelta(minutes=5),
            duration_ms=10.0,
            success=False,
            block_type=BlockType.SNI_BLOCK,
        )
    )
    recent = store.reports_since(since=now - timedelta(minutes=30))
    assert len(recent) == 1
    assert recent[0].block_type is BlockType.SNI_BLOCK


def test_incident_upsert_overwrites(store: Store) -> None:
    inc = Incident(
        id="abc",
        profile_id="p",
        vantage="v",
        block_type=BlockType.SNI_BLOCK,
        severity=IncidentSeverity.MEDIUM,
        confidence=0.7,
        started_at=utcnow() - timedelta(minutes=10),
        last_seen_at=utcnow() - timedelta(minutes=5),
        sample_count=10,
        failure_rate=0.7,
        summary="initial",
        suggested_recipes=["rotate_sni_pool"],
    )
    store.upsert_incident(inc)
    inc2 = inc.model_copy(update={"summary": "updated", "sample_count": 20})
    store.upsert_incident(inc2)
    [back] = store.incidents_recent()
    assert back.summary == "updated"
    assert back.sample_count == 20
