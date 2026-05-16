"""24/7 fast/slow loop tying probes → detector → store together."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .detector import detect_incidents
from .probe import Vantage, run_batch
from .store import Store
from .types import utcnow

logger = logging.getLogger(__name__)


class HealerScheduler:
    """Orchestrates the recurring loops.

    fast_loop:  probes → store → detect → store incidents.
    slow_loop:  re-evaluate older window for slow degradations.
    """

    def __init__(
        self,
        store: Store,
        vantage: Vantage,
        *,
        fast_interval_minutes: int = 5,
        slow_interval_minutes: int = 60,
        concurrency: int = 16,
    ) -> None:
        self.store = store
        self.vantage = vantage
        self.fast_interval_minutes = fast_interval_minutes
        self.slow_interval_minutes = slow_interval_minutes
        self.concurrency = concurrency
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        self._scheduler.add_job(
            self.fast_loop,
            "interval",
            minutes=self.fast_interval_minutes,
            id="fast_loop",
            next_run_time=utcnow(),
        )
        self._scheduler.add_job(
            self.slow_loop,
            "interval",
            minutes=self.slow_interval_minutes,
            id="slow_loop",
        )
        self._scheduler.start()
        logger.info(
            "scheduler started: fast=%dm slow=%dm",
            self.fast_interval_minutes,
            self.slow_interval_minutes,
        )

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    async def fast_loop(self) -> None:
        from datetime import timedelta

        profiles = self.store.list_profiles()
        if not profiles:
            logger.debug("fast_loop: no profiles")
            return
        try:
            reports = await run_batch(profiles, self.vantage, concurrency=self.concurrency)
        except Exception:  # noqa: BLE001
            logger.exception("fast_loop: probe batch failed")
            return
        for r in reports:
            self.store.insert_report(r)
        recent = self.store.reports_since(since=utcnow() - timedelta(minutes=30))
        incidents = detect_incidents(recent)
        for inc in incidents:
            self.store.upsert_incident(inc)
        logger.info("fast_loop: %d reports, %d incidents", len(reports), len(incidents))

    async def slow_loop(self) -> None:
        from datetime import timedelta

        recent = self.store.reports_since(since=utcnow() - timedelta(hours=6))
        incidents = detect_incidents(
            recent, window_minutes=6 * 60, min_samples=20, failure_threshold=0.2
        )
        for inc in incidents:
            self.store.upsert_incident(inc)

        # Passive ("always-on") training: even when AIMA_AUTO_APPLY=0 we still
        # want the dashboard to surface what the detector keeps recommending
        # for each (vantage's ASN, block_type) pair. Increment a weak signal
        # for every suggested recipe of every active incident in this batch.
        observations = 0
        for inc in incidents:
            asn = self._asn_for_vantage(inc.vantage)
            for recipe_id in inc.suggested_recipes:
                self.store.record_observation(
                    asn=asn,
                    block_type=inc.block_type,
                    recipe_id=recipe_id,
                    note=f"slow_loop@{inc.id}",
                )
                observations += 1

        logger.info(
            "slow_loop: %d reports, %d incidents, %d observations recorded",
            len(recent),
            len(incidents),
            observations,
        )

    def _asn_for_vantage(self, vantage_name: str | None) -> int | None:
        """Map an incident's vantage label back to an ASN, when known.

        Today the only vantage we know about is the local one (``self.vantage``);
        external vantages would need their own lookup. Returning ``None`` means
        "global / unspecified" and is recorded under ASN ``-1``.
        """

        if vantage_name and vantage_name == self.vantage.name:
            return self.vantage.asn
        return None
