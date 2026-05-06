"""Minimal FastAPI surface for AIMA.

Exposes both:
  * `create_app()` — standalone uvicorn entrypoint (used by `aima serve`)
  * `build_router(store_factory, vantage_factory)` — mountable APIRouter so
    the existing XSERVIS backend can include `/aima/...` without changing the
    host's app object. See `integration/xservis_loader.py`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import APIRouter, FastAPI, HTTPException

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


def build_router(
    store_factory: Callable[[], Store],
    vantage_factory: Callable[[], Vantage] = _vantage_from_env,
) -> APIRouter:
    """Build an APIRouter that exposes the AIMA endpoints.

    The factories are called per-request so the router stays decoupled from
    the lifecycle (good for embedding into an existing app).
    """

    router = APIRouter()

    @router.get("/health")
    async def health() -> dict:
        return {
            "ok": True,
            "vantage": vantage_factory().name,
            "now": utcnow().isoformat(),
        }

    @router.get("/profiles")
    async def list_profiles() -> list[ProbeProfile]:
        return store_factory().list_profiles()

    @router.put("/profiles/{profile_id}")
    async def upsert_profile(profile_id: str, profile: ProbeProfile) -> ProbeProfile:
        if profile.id != profile_id:
            raise HTTPException(400, "id mismatch")
        store_factory().upsert_profile(profile)
        return profile

    @router.post("/probe/report", status_code=201)
    async def post_report(report: ProbeReport) -> dict:
        store_factory().insert_report(report)
        return {"ok": True}

    @router.post("/probe/reports", status_code=201)
    async def post_reports(reports: list[ProbeReport]) -> dict:
        store_factory().insert_reports(reports)
        return {"ok": True, "count": len(reports)}

    @router.get("/incidents")
    async def get_incidents(*, max_age_minutes: int = 60) -> list[Incident]:
        return store_factory().incidents_recent(max_age_minutes=max_age_minutes)

    @router.post("/detect/run")
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


# Importable for `uvicorn aima.api:app`.
app = create_app(run_scheduler=False)
