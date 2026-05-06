"""Minimal FastAPI surface so external probes can report in and clients can poll incidents."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

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


def create_app(*, db_path: str | None = None, run_scheduler: bool = True) -> FastAPI:
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

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "vantage": vantage.name, "now": utcnow().isoformat()}

    @app.get("/api/profiles")
    async def list_profiles() -> list[ProbeProfile]:
        return store.list_profiles()

    @app.put("/api/profiles/{profile_id}")
    async def upsert_profile(profile_id: str, profile: ProbeProfile) -> ProbeProfile:
        if profile.id != profile_id:
            raise HTTPException(400, "id mismatch")
        store.upsert_profile(profile)
        return profile

    @app.post("/api/probe/report", status_code=201)
    async def post_report(report: ProbeReport) -> dict:
        store.insert_report(report)
        return {"ok": True}

    @app.post("/api/probe/reports", status_code=201)
    async def post_reports(reports: list[ProbeReport]) -> dict:
        store.insert_reports(reports)
        return {"ok": True, "count": len(reports)}

    @app.get("/api/incidents")
    async def get_incidents(*, max_age_minutes: int = 60) -> list[Incident]:
        return store.incidents_recent(max_age_minutes=max_age_minutes)

    @app.post("/api/detect/run")
    async def run_detector(*, window_minutes: int = 30) -> dict:
        from datetime import timedelta

        reports = store.reports_since(since=utcnow() - timedelta(minutes=window_minutes))
        incidents = detect_incidents(reports, window_minutes=window_minutes)
        for inc in incidents:
            store.upsert_incident(inc)
        return {"reports": len(reports), "incidents": len(incidents)}

    return app


# Importable for `uvicorn aima.api:app`.
app = create_app(run_scheduler=False)
