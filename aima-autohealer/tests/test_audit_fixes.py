"""Regression tests for the 2026-11 audit fixes."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aima.apply import ApplyConfig, apply_incident
from aima.snapshot import SnapshotStore, restore_snapshot, take_snapshot
from aima.store import Store
from aima.types import BlockType, ProbeReport
from tests.test_apply import FakeXUI, _incident, _profiles, _reality_inbound, _vantage


@pytest.mark.asyncio
async def test_restore_keeps_clients_added_after_snapshot(tmp_path: Path) -> None:
    ib = _reality_inbound()
    ib["settings"] = json.dumps({"clients": [{"id": "old", "email": "a"}]})
    ib["up"], ib["down"] = 10, 20
    fake = FakeXUI([ib])
    store = SnapshotStore(tmp_path / "snaps")
    snap = await take_snapshot(fake, note="t", store=store)  # type: ignore[arg-type]

    # a recipe changes the port, meanwhile the shop adds a paying client and traffic grows
    live = fake._inbounds[1]
    live["port"] = 8443
    live["settings"] = json.dumps({"clients": [{"id": "old", "email": "a"}, {"id": "new", "email": "b"}]})
    live["up"], live["down"] = 500, 900

    await restore_snapshot(fake, snap.snapshot_id, store=store)  # type: ignore[arg-type]
    restored = fake._inbounds[1]
    assert restored["port"] == 443
    assert len(json.loads(restored["settings"])["clients"]) == 2
    assert (restored["up"], restored["down"]) == (500, 900)


@pytest.mark.asyncio
async def test_restore_can_target_one_inbound(tmp_path: Path) -> None:
    fake = FakeXUI([{"id": 1, "port": 443}, {"id": 2, "port": 443}])
    store = SnapshotStore(tmp_path / "snaps")
    snap = await take_snapshot(fake, note="t", store=store)  # type: ignore[arg-type]
    fake._inbounds[1]["port"] = 1
    fake._inbounds[2]["port"] = 2  # changed by an admin, must stay
    n = await restore_snapshot(fake, snap.snapshot_id, store=store, inbound_ids={1})  # type: ignore[arg-type]
    assert n == 1
    assert fake._inbounds[1]["port"] == 443 and fake._inbounds[2]["port"] == 2


def test_snapshot_id_is_validated(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snaps")
    for bad in ("../../etc/passwd", "abc", "", "0123456789ab/x"):
        with pytest.raises(ValueError):
            store.path_for(bad)
    assert store.path_for("0123456789ab").name == "0123456789ab.json"


@pytest.mark.asyncio
async def test_snapshot_files_are_private(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snaps")
    snap = await take_snapshot(FakeXUI([_reality_inbound()]), note="t", store=store)  # type: ignore[arg-type]
    mode = stat.S_IMODE(os.stat(store.path_for(snap.snapshot_id)).st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(os.stat(store.root).st_mode) == 0o700
    assert not list(store.root.glob(".snap-*"))  # no temp files left behind


@pytest.mark.asyncio
async def test_failed_recipe_is_reverted_before_next_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeXUI([_reality_inbound()])
    calls = {"n": 0}

    async def fake_run_batch(profiles, vantage, *, concurrency=16):  # noqa: ANN001
        calls["n"] += 1
        ok = calls["n"] >= 2  # first recipe does not help, second does
        return [
            ProbeReport(profile_id="p1", vantage="t", started_at=datetime.now(UTC), duration_ms=5,
                        success=ok, block_type=BlockType.NONE if ok else BlockType.SNI_BLOCK)
            for _ in range(8)
        ]

    monkeypatch.setattr("aima.apply.run_batch", fake_run_batch)
    store = Store(tmp_path / "t.db")
    try:
        result = await apply_incident(
            incident=_incident(fail=0.9, recipes=["switch_to_alt_port_8443_2053", "rotate_sni_pool"]),
            inbound_id=1,
            profiles=_profiles(),
            vantage=_vantage(),
            xui=fake,  # type: ignore[arg-type]
            store=store,
            snap_store=SnapshotStore(tmp_path / "snaps"),
            cfg=ApplyConfig(settle_seconds=0, verify_min_samples=4),
        )
    finally:
        store.close()
    assert result.recipe_kept == "rotate_sni_pool"
    # the useless port change from the first recipe must not survive
    assert fake._inbounds[1]["port"] == 443


@pytest.mark.asyncio
async def test_del_client_quotes_email(httpx_mock) -> None:  # noqa: ANN001
    from aima.xui_client import XUIClient, XUICreds

    httpx_mock.add_response(url="http://panel.local/login", json={"success": True})
    httpx_mock.add_response(
        url="http://panel.local/panel/api/inbounds/3/delClient/a%2Fb%3Fc%40x", json={"success": True}
    )
    async with XUIClient(XUICreds("http://panel.local", "u", "p")) as c:
        await c.del_client(3, "a/b?c@x")


def _client(tmp_path: Path, token: str | None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aima.api import build_router

    store = Store(tmp_path / "api.db")
    app = FastAPI()
    app.include_router(build_router(lambda: store, api_token=token), prefix="/api")
    return TestClient(app), store


PROFILE = {"id": "p1", "label": "x", "kind": "direct_tls", "host": "example.com", "port": 443}


def test_api_writes_need_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, store = _client(tmp_path, "s3cret")
    try:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/profiles").status_code == 401
        assert c.put("/api/profiles/p1", json=PROFILE).status_code == 401
        assert c.put("/api/profiles/p1", json=PROFILE, headers={"X-API-Key": "nope"}).status_code == 401
        ok = c.put("/api/profiles/p1", json=PROFILE, headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200
        assert c.get("/api/profiles", headers={"X-API-Key": "s3cret"}).json()[0]["id"] == "p1"
    finally:
        store.close()


def test_api_without_token_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIMA_API_ALLOW_UNAUTH_WRITES", raising=False)
    c, store = _client(tmp_path, "")
    try:
        assert c.get("/api/profiles").status_code == 200
        assert c.put("/api/profiles/p1", json=PROFILE).status_code == 503
        assert c.post("/api/detect/run").status_code == 503
    finally:
        store.close()
    monkeypatch.setenv("AIMA_API_ALLOW_UNAUTH_WRITES", "1")
    c, store = _client(tmp_path, "")
    try:
        assert c.put("/api/profiles/p1", json=PROFILE).status_code == 200
    finally:
        store.close()


def test_importing_api_does_not_create_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AIMA_DB", raising=False)
    import aima.api as api_mod

    importlib.reload(api_mod)
    assert not (tmp_path / "aima.db").exists()
