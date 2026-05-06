"""Tests for the apply orchestrator (snapshot → mutate → re-probe → keep/rollback)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aima.apply import (
    ApplyConfig,
    apply_incident,
    order_recipes_for_incident,
)
from aima.mutation_engine import SNI_POOLS
from aima.probe import Vantage
from aima.snapshot import SnapshotStore
from aima.store import Store
from aima.types import (
    BlockType,
    Incident,
    IncidentSeverity,
    ProbeProfile,
    ProbeReport,
    TransportKind,
)

# ─── Fakes ──────────────────────────────────────────────────────────────────


class FakeXUI:
    """In-memory fake of XUIClient that supports the methods apply.py uses."""

    def __init__(self, inbounds: list[dict]) -> None:
        self._inbounds = {int(ib["id"]): json.loads(json.dumps(ib)) for ib in inbounds}

    async def list_inbounds(self) -> list[dict]:
        return list(self._inbounds.values())

    async def get_inbound(self, inbound_id: int) -> dict:
        return self._inbounds[inbound_id]

    async def update_inbound(self, inbound_id: int, ib: dict) -> dict:
        self._inbounds[inbound_id] = ib
        return {"updated": True}


def _reality_inbound() -> dict:
    return {
        "id": 1,
        "port": 443,
        "protocol": "vless",
        "streamSettings": json.dumps(
            {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "dest": f"{SNI_POOLS[0][0]}:443",
                    "serverNames": list(SNI_POOLS[0]),
                    "shortIds": ["aaaaaaaa"],
                    "privateKey": "k",
                    "publicKey": "p",
                },
            }
        ),
    }


def _profiles() -> list[ProbeProfile]:
    return [
        ProbeProfile(
            id="p1",
            label="reality",
            kind=TransportKind.DIRECT_TLS,
            host="127.0.0.1",
            port=443,
            sni="example.com",
        )
    ]


def _vantage() -> Vantage:
    return Vantage(name="t", asn=1, provider="t", region="t")


def _incident(*, fail: float, recipes: list[str]) -> Incident:
    now = datetime.now(UTC)
    return Incident(
        id="inc1",
        profile_id="p1",
        vantage="t",
        block_type=BlockType.SNI_BLOCK,
        severity=IncidentSeverity.HIGH,
        confidence=0.9,
        started_at=now - timedelta(minutes=10),
        last_seen_at=now,
        sample_count=10,
        failure_rate=fail,
        summary="test",
        suggested_recipes=recipes,
    )


@pytest.fixture
def tmp_store(tmp_path: Path) -> Iterator[Store]:
    store = Store(tmp_path / "test.db")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def tmp_snap(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "snaps")


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_order_recipes_prefers_suggested_then_default() -> None:
    inc = _incident(fail=0.9, recipes=["fallback_cdn_ws"])
    out = order_recipes_for_incident(inc)
    assert out[0] == "fallback_cdn_ws"
    assert "rotate_sni_pool" in out


def test_order_recipes_uses_learned_priority() -> None:
    inc = _incident(fail=0.9, recipes=[])
    learned = {(None, BlockType.SNI_BLOCK, "switch_to_xhttp_path"): 0.9}
    out = order_recipes_for_incident(inc, learned_priority=learned)
    assert out[0] == "switch_to_xhttp_path"


@pytest.mark.asyncio
async def test_apply_keeps_first_recipe_when_failure_rate_drops(
    monkeypatch: pytest.MonkeyPatch,
    tmp_store: Store,
    tmp_snap: SnapshotStore,
) -> None:
    fake = FakeXUI([_reality_inbound()])

    async def fake_run_batch(profiles, vantage, *, concurrency=16):  # noqa: ANN001
        return [
            ProbeReport(
                profile_id="p1",
                vantage="t",
                started_at=datetime.now(UTC),
                duration_ms=20,
                success=True,
                block_type=BlockType.NONE,
            )
            for _ in range(8)
        ]

    monkeypatch.setattr("aima.apply.run_batch", fake_run_batch)

    inc = _incident(fail=0.9, recipes=["rotate_sni_pool"])
    cfg = ApplyConfig(settle_seconds=0, verify_min_samples=4)
    result = await apply_incident(
        incident=inc,
        inbound_id=1,
        profiles=_profiles(),
        vantage=_vantage(),
        xui=fake,  # type: ignore[arg-type]
        store=tmp_store,
        snap_store=tmp_snap,
        cfg=cfg,
    )
    assert result.recipe_kept == "rotate_sni_pool"
    assert result.rolled_back is False
    # Inbound should now have a different SNI pool
    new_settings = json.loads(fake._inbounds[1]["streamSettings"])
    assert new_settings["realitySettings"]["serverNames"] != list(SNI_POOLS[0])


@pytest.mark.asyncio
async def test_apply_rolls_back_when_no_recipe_helps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_store: Store,
    tmp_snap: SnapshotStore,
) -> None:
    original = _reality_inbound()
    fake = FakeXUI([original])

    async def fake_run_batch(profiles, vantage, *, concurrency=16):  # noqa: ANN001
        return [
            ProbeReport(
                profile_id="p1",
                vantage="t",
                started_at=datetime.now(UTC),
                duration_ms=20,
                success=False,
                block_type=BlockType.SNI_BLOCK,
            )
            for _ in range(8)
        ]

    monkeypatch.setattr("aima.apply.run_batch", fake_run_batch)

    inc = _incident(fail=0.9, recipes=["rotate_sni_pool", "regenerate_short_ids"])
    cfg = ApplyConfig(settle_seconds=0, verify_min_samples=4, improvement_delta=0.4)
    result = await apply_incident(
        incident=inc,
        inbound_id=1,
        profiles=_profiles(),
        vantage=_vantage(),
        xui=fake,  # type: ignore[arg-type]
        store=tmp_store,
        snap_store=tmp_snap,
        cfg=cfg,
    )
    assert result.recipe_kept is None
    assert result.rolled_back is True
    # original SNI pool restored
    restored = json.loads(fake._inbounds[1]["streamSettings"])
    assert restored["realitySettings"]["serverNames"] == list(SNI_POOLS[0])


@pytest.mark.asyncio
async def test_apply_dry_run_does_not_push(
    monkeypatch: pytest.MonkeyPatch,
    tmp_store: Store,
    tmp_snap: SnapshotStore,
) -> None:
    fake = FakeXUI([_reality_inbound()])
    pushed = []

    async def spy_update(inbound_id, ib):  # noqa: ANN001
        pushed.append((inbound_id, ib))
        return {}

    monkeypatch.setattr(fake, "update_inbound", spy_update)

    inc = _incident(fail=0.9, recipes=["rotate_sni_pool"])
    cfg = ApplyConfig(dry_run=True, settle_seconds=0)
    result = await apply_incident(
        incident=inc,
        inbound_id=1,
        profiles=_profiles(),
        vantage=_vantage(),
        xui=fake,  # type: ignore[arg-type]
        store=tmp_store,
        snap_store=tmp_snap,
        cfg=cfg,
    )
    assert result.recipe_kept == "rotate_sni_pool"
    assert pushed == []
    assert result.rolled_back is False
