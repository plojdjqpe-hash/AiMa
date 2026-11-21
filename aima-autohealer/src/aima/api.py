"""Minimal FastAPI surface for AIMA.

Exposes both:
  * `create_app()` — standalone uvicorn entrypoint (used by `aima serve`)
  * `build_router(store_factory, vantage_factory)` — mountable APIRouter so
    the existing XSERVIS backend can include `/aima/...` without changing the
    host's app object. See `integration/xservis_loader.py`.
"""

from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException

from .detector import detect_incidents
from .probe import Vantage
from .scheduler import HealerScheduler
from .store import Store
from .types import Incident, ProbeProfile, ProbeReport, utcnow


def _vantage_from_env() -> Vantage:
    return Vantage(
        name=os.environ.get("AIMA_VANTAGE_NAME", "local-vm"),
        asn=int(os.environ["AIMA_VANTAGE_ASN"]) if "AIMA_VANTAGE_ASN" in os.environ else None,
        provider=os.environ.get("AIMA_VANTAGE_PROVIDER"),
        region=os.environ.get("AIMA_VANTAGE_REGION"),
    )


logger = logging.getLogger(__name__)


def _token_guard(token: str | None) -> Callable[..., None]:
    """Dependency enforcing ``Authorization: Bearer <AIMA_API_TOKEN>`` (or ``X-API-Key``).

    Without a token configured, reads stay open but writes (new probe targets, fake
    reports, detector runs) are refused: an open PUT /profiles lets anyone make the VPN
    server probe arbitrary hosts, and fake reports can poison incident detection.
    Set AIMA_API_ALLOW_UNAUTH_WRITES=1 to restore the old open behaviour on a trusted network.
    """

    expected = token if token is not None else os.environ.get("AIMA_API_TOKEN", "")
    allow_open_writes = os.environ.get("AIMA_API_ALLOW_UNAUTH_WRITES", "") == "1"

    def guard(
        authorization: str | None = Header(None),
        x_api_key: str | None = Header(None),
        *,
        write: bool = False,
    ) -> None:
        if not expected:
            if write and not allow_open_writes:
                raise HTTPException(503, "set AIMA_API_TOKEN to enable write endpoints")
            return
        given = x_api_key or ""
        if authorization and authorization.lower().startswith("bearer "):
            given = authorization[7:].strip()
        if not given or not hmac.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(401, "invalid or missing API token")

    return guard


def build_router(
    store_factory: Callable[[], Store],
    vantage_factory: Callable[[], Vantage] = _vantage_from_env,
    *,
    api_token: str | None = None,
) -> APIRouter:
    """Build an APIRouter that exposes the AIMA endpoints.

    The factories are called per-request so the router stays decoupled from
    the lifecycle (good for embedding into an existing app).
    ``api_token`` defaults to the AIMA_API_TOKEN env var (see ``_token_guard``).
    """

    guard = _token_guard(api_token)

    def can_read(authorization: str | None = Header(None), x_api_key: str | None = Header(None)) -> None:
        guard(authorization, x_api_key)

    def can_write(authorization: str | None = Header(None), x_api_key: str | None = Header(None)) -> None:
        guard(authorization, x_api_key, write=True)

    R = [Depends(can_read)]
    W = [Depends(can_write)]
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict:
        return {
            "ok": True,
            "vantage": vantage_factory().name,
            "now": utcnow().isoformat(),
        }

    @router.get("/profiles", dependencies=R)
    async def list_profiles() -> list[ProbeProfile]:
        return store_factory().list_profiles()

    @router.put("/profiles/{profile_id}", dependencies=W)
    async def upsert_profile(profile_id: str, profile: ProbeProfile) -> ProbeProfile:
        if profile.id != profile_id:
            raise HTTPException(400, "id mismatch")
        store_factory().upsert_profile(profile)
        return profile

    @router.post("/probe/report", status_code=201, dependencies=W)
    async def post_report(report: ProbeReport) -> dict:
        store_factory().insert_report(report)
        return {"ok": True}

    @router.post("/probe/reports", status_code=201, dependencies=W)
    async def post_reports(reports: list[ProbeReport]) -> dict:
        store_factory().insert_reports(reports)
        return {"ok": True, "count": len(reports)}

    @router.get("/incidents", dependencies=R)
    async def get_incidents(*, max_age_minutes: int = 60) -> list[Incident]:
        return store_factory().incidents_recent(max_age_minutes=max_age_minutes)

    @router.post("/detect/run", dependencies=W)
    async def run_detector(*, window_minutes: int = 30) -> dict:
        store = store_factory()
        reports = store.reports_since(since=utcnow() - timedelta(minutes=window_minutes))
        incidents = detect_incidents(reports, window_minutes=window_minutes)
        for inc in incidents:
            store.upsert_incident(inc)
        return {"reports": len(reports), "incidents": len(incidents)}

    return router


def create_app(*, db_path: str | None = None, run_scheduler: bool = True) -> FastAPI:
    """Standalone app for `aima serve` / `uvicorn aima.api:app`."""

    store = Store(db_path or os.environ.get("AIMA_DB", "aima.db"))
    vantage = _vantage_from_env()
    scheduler = HealerScheduler(store, vantage)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if run_scheduler:
            scheduler.start()
        try:
            yield
        finally:
            if run_scheduler:
                scheduler.shutdown()
            store.close()

    app = FastAPI(title="AiMa Auto-Healer (prototype)", lifespan=lifespan)
    app.include_router(
        build_router(lambda: store, lambda: vantage),
        prefix="/api",
    )
    return app


# `uvicorn aima.api:app` still works, but the app (and its sqlite file) is only created
# when `app` is actually accessed. Building it at import time created ./aima.db in the
# working directory of anything that merely imported this module (e.g. the XSERVIS loader).
_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    global _app
    if name == "app":
        if _app is None:
            _app = create_app(run_scheduler=False)
        return _app
    raise AttributeError(name)
