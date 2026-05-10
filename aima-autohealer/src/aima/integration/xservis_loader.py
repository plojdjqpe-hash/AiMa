"""Wire the AIMA auto-healer into the existing XSERVIS FastAPI backend.

This module exposes a single function `attach(app)` that the host backend's
`main.py` calls during startup. The host backend keeps its own routes,
scheduler jobs, and `ai_telemetry_job`; this module **adds** the auto-healer
without modifying any of them.

Only environment variables — no hard-coded secrets:

    AIMA_ENABLED            — "1" to attach (default "1")
    AIMA_DB_PATH            — sqlite path, default /opt/xservis/data/aima.db
    AIMA_SNAPSHOT_DIR       — snapshot dir, default /opt/xservis/data/aima_snapshots
    AIMA_FAST_LOOP_MINUTES  — probe cadence (default 5)
    AIMA_SLOW_LOOP_MINUTES  — trend cadence (default 60)
    AIMA_AUTO_APPLY         — "1" to actually mutate inbounds; "0" = detect-only
    AIMA_VANTAGE_NAME / ASN / PROVIDER / REGION
    XUI_BASE_URL / XUI_USERNAME / XUI_PASSWORD — 3X-UI creds (read at runtime)

If env-vars are missing or AIMA_ENABLED!=1, attach() logs a warning and is
a no-op so it can never break the host startup.

The host backend's `main.py` does:

    from aima.integration.xservis_loader import attach
    attach(app)

That single line is enough — backwards-compatible if aima isn't installed:

    try:
        from aima.integration.xservis_loader import attach
        attach(app)
    except ImportError:
        pass
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from ..admin import build_admin_router
from ..api import build_router
from ..probe import Vantage
from ..scheduler import HealerScheduler
from ..store import Store

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _bool_env(key: str, *, default: bool = True) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip() not in ("0", "", "false", "False", "no", "off")


def _vantage_from_env() -> Vantage:
    return Vantage(
        name=os.environ.get("AIMA_VANTAGE_NAME", "xs11"),
        asn=int(os.environ["AIMA_VANTAGE_ASN"]) if "AIMA_VANTAGE_ASN" in os.environ else None,
        provider=os.environ.get("AIMA_VANTAGE_PROVIDER"),
        region=os.environ.get("AIMA_VANTAGE_REGION"),
    )


def attach(app: FastAPI) -> bool:
    """Attach AIMA to an existing FastAPI app.

    Returns True if attached, False if disabled / misconfigured.
    Never raises — the host backend must remain up regardless of AIMA state.
    """

    try:
        if not _bool_env("AIMA_ENABLED", default=True):
            logger.info("aima: AIMA_ENABLED=0, skipping attach")
            return False

        db_path = os.environ.get("AIMA_DB_PATH", "/opt/xservis/data/aima.db")
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        store = Store(db_path)
        vantage = _vantage_from_env()

        fast_minutes = int(os.environ.get("AIMA_FAST_LOOP_MINUTES", "5"))
        slow_minutes = int(os.environ.get("AIMA_SLOW_LOOP_MINUTES", "60"))
        sched = HealerScheduler(
            store,
            vantage,
            fast_interval_minutes=fast_minutes,
            slow_interval_minutes=slow_minutes,
        )

        @app.on_event("startup")  # noqa: D401 — FastAPI lifecycle decorator
        async def _aima_startup() -> None:
            logger.info(
                "aima: starting scheduler (fast=%dmin, slow=%dmin, auto_apply=%s)",
                fast_minutes,
                slow_minutes,
                _bool_env("AIMA_AUTO_APPLY", default=False),
            )
            try:
                sched.start()
            except Exception:
                logger.exception("aima: scheduler failed to start")

        @app.on_event("shutdown")
        async def _aima_shutdown() -> None:
            try:
                sched.shutdown()
            except Exception:
                logger.exception("aima: scheduler shutdown failed")

        app.include_router(
            build_router(lambda: store, lambda: vantage),
            prefix="/aima",
            tags=["aima"],
        )
        app.include_router(
            build_admin_router(lambda: store),
            prefix="/aima/admin",
            tags=["aima-admin"],
        )

        logger.info(
            "aima: attached at /aima (+ /aima/admin), db=%s, vantage=%s",
            db_path,
            vantage.name,
        )
        return True
    except Exception:
        # Catch-all: AIMA must never break the host startup.
        logger.exception("aima: attach failed; running without auto-healer")
        return False


__all__ = ["attach"]
