"""Tests for the SnapshotStore + take/restore round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aima.snapshot import SnapshotStore, restore_snapshot, take_snapshot


class FakeXUI:
    def __init__(self, inbounds: list[dict]) -> None:
        self._inbounds = {int(ib["id"]): json.loads(json.dumps(ib)) for ib in inbounds}

    async def list_inbounds(self) -> list[dict]:
        return list(self._inbounds.values())

    async def update_inbound(self, ib_id: int, ib: dict) -> dict:
        self._inbounds[ib_id] = ib
        return {}


@pytest.mark.asyncio
async def test_take_then_restore_round_trip(tmp_path: Path) -> None:
    initial = [{"id": 1, "port": 443}, {"id": 2, "port": 8443}]
    fake = FakeXUI(initial)
    store = SnapshotStore(tmp_path / "snaps")

    snap = await take_snapshot(fake, note="test", store=store)  # type: ignore[arg-type]
    assert snap.snapshot_id

    # Mutate
    fake._inbounds[1]["port"] = 9999

    n = await restore_snapshot(fake, snap.snapshot_id, store=store)  # type: ignore[arg-type]
    assert n == 2
    assert fake._inbounds[1]["port"] == 443


@pytest.mark.asyncio
async def test_take_snapshot_persists_file(tmp_path: Path) -> None:
    fake = FakeXUI([{"id": 7, "port": 443}])
    store = SnapshotStore(tmp_path / "snaps")
    snap = await take_snapshot(fake, note="abc", store=store)  # type: ignore[arg-type]
    p = store.path_for(snap.snapshot_id)
    assert p.exists()
    raw = json.loads(p.read_text())
    assert raw["note"] == "abc"
    assert raw["inbounds"] == [{"id": 7, "port": 443}]
