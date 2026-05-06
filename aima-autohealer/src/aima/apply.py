"""Atomic apply orchestrator.

Given an `Incident` and an ordered list of recipe ids:

    snapshot → for each recipe in priority order:
        mutate inbound (pure) → push to 3X-UI → wait `settle_seconds` → re-probe
        if probe verdict is BETTER than the incident's failure_rate: keep & record success
        else: continue to next recipe
    if all recipes exhausted: restore snapshot and record exhausted

This module is the only place that combines mutations + network calls. It is
also the only place that records `LearnedRule` rows: per (asn, block_type,
recipe_id) success/failure counters that feed back into recipe priority.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from .detector import RECIPE_BY_BLOCK
from .mutation_engine import RecipeContext, get_handler
from .probe import Vantage, run_batch
from .snapshot import Snapshot, SnapshotStore, restore_snapshot, take_snapshot
from .store import Store
from .types import BlockType, Incident, ProbeProfile, ProbeReport, utcnow
from .xui_client import XUIClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplyResult:
    incident_id: str
    recipe_attempted: list[str] = field(default_factory=list)
    recipe_kept: str | None = None
    snapshot_id: str | None = None
    rolled_back: bool = False
    final_failure_rate: float | None = None
    notes: str = ""


@dataclass(slots=True)
class ApplyConfig:
    settle_seconds: float = 30.0
    """How long to wait between mutation and re-probe."""

    verify_min_samples: int = 6
    """Minimum probes the re-probe must produce before we trust its verdict."""

    improvement_delta: float = 0.4
    """Failure-rate must drop by at least this much for a recipe to be 'kept'."""

    dry_run: bool = False
    """If True, mutations are computed and logged but never pushed to 3X-UI."""


def order_recipes_for_incident(
    incident: Incident,
    *,
    learned_priority: dict[tuple[int | None, BlockType, str], float] | None = None,
) -> list[str]:
    """Return recipe ids in the order we should try them for this incident.

    Priority:
        1. recipes the user explicitly suggested in the Incident
        2. learned high-success recipes for (asn, block_type) — from telemetry
        3. canonical defaults from RECIPE_BY_BLOCK[incident.block_type]
    """

    suggested = list(dict.fromkeys(incident.suggested_recipes))
    defaults = list(RECIPE_BY_BLOCK.get(incident.block_type, []))
    learned: list[str] = []
    if learned_priority is not None:
        # filter to (asn, block_type) entries and sort by score desc
        scored = [
            (rid, score)
            for (asn, bt, rid), score in learned_priority.items()
            if bt == incident.block_type
        ]
        scored.sort(key=lambda kv: kv[1], reverse=True)
        learned = [rid for rid, _ in scored]
    seen: set[str] = set()
    out: list[str] = []
    for source in (suggested, learned, defaults):
        for rid in source:
            if rid not in seen:
                seen.add(rid)
                out.append(rid)
    return out


def _failure_rate(reports: Iterable[ProbeReport]) -> tuple[int, float]:
    rs = list(reports)
    if not rs:
        return 0, 0.0
    failed = sum(1 for r in rs if not r.success)
    return len(rs), failed / len(rs)


async def _apply_one(
    xui: XUIClient,
    inbound_id: int,
    recipe_id: str,
    ctx: RecipeContext,
    *,
    cfg: ApplyConfig,
) -> tuple[bool, str]:
    """Push one recipe's mutation to 3X-UI. Returns (changed, notes)."""

    handler = get_handler(recipe_id)
    inbound = await xui.get_inbound(inbound_id)
    result = await handler(inbound, ctx)
    if not result.changed:
        return False, f"{recipe_id}: skipped ({result.notes})"
    if cfg.dry_run:
        logger.info("dry_run %s -> %s", recipe_id, result.notes)
        return True, f"dry_run {recipe_id}: {result.notes}"
    await xui.update_inbound(inbound_id, result.inbound)
    logger.info("applied %s -> %s", recipe_id, result.notes)
    return True, f"{recipe_id}: {result.notes}"


async def apply_incident(
    *,
    incident: Incident,
    inbound_id: int,
    profiles: list[ProbeProfile],
    vantage: Vantage,
    xui: XUIClient,
    store: Store,
    snap_store: SnapshotStore | None = None,
    cfg: ApplyConfig | None = None,
) -> ApplyResult:
    """Try recipes one by one until one improves the failure rate, else roll back."""

    cfg = cfg or ApplyConfig()
    snap_store = snap_store or SnapshotStore()
    result = ApplyResult(incident_id=incident.id)

    snap = await take_snapshot(
        xui,
        note=f"pre-apply {incident.id} ({incident.block_type})",
        store=snap_store,
    )
    result.snapshot_id = snap.snapshot_id

    recipes = order_recipes_for_incident(
        incident, learned_priority=store.learned_priority_map()
    )
    if not recipes:
        result.notes = "no recipes available for this block_type"
        return result

    base_failure = incident.failure_rate
    ctx = RecipeContext(
        block_type=incident.block_type,
        profile_id=incident.profile_id,
        vantage=incident.vantage,
        asn=None,
    )

    for recipe_id in recipes:
        result.recipe_attempted.append(recipe_id)
        try:
            changed, notes = await _apply_one(xui, inbound_id, recipe_id, ctx, cfg=cfg)
        except Exception as exc:  # noqa: BLE001 — we intentionally catch broadly
            logger.exception("recipe %s raised", recipe_id)
            await _safe_restore(xui, snap, snap_store)
            result.rolled_back = True
            result.notes = f"{recipe_id}: raised {type(exc).__name__}: {exc}"
            store.record_recipe_outcome(
                asn=None,
                block_type=incident.block_type,
                recipe_id=recipe_id,
                success=False,
                note=str(exc),
            )
            return result

        if not changed:
            store.record_recipe_outcome(
                asn=None,
                block_type=incident.block_type,
                recipe_id=recipe_id,
                success=False,
                note="recipe declined to mutate (exhausted/incompatible)",
            )
            continue

        if cfg.dry_run:
            result.recipe_kept = recipe_id
            result.notes = f"dry_run kept {recipe_id} ({notes})"
            return result

        await asyncio.sleep(cfg.settle_seconds)
        new_reports = await run_batch(profiles, vantage)
        store.insert_reports(new_reports)
        n, fail_rate = _failure_rate(new_reports)
        if n < cfg.verify_min_samples:
            logger.info(
                "verify: only %d samples for recipe %s, treating as inconclusive",
                n,
                recipe_id,
            )
            store.record_recipe_outcome(
                asn=None,
                block_type=incident.block_type,
                recipe_id=recipe_id,
                success=False,
                note=f"verify inconclusive ({n} samples)",
            )
            continue

        result.final_failure_rate = fail_rate
        improved = (base_failure - fail_rate) >= cfg.improvement_delta
        store.record_recipe_outcome(
            asn=None,
            block_type=incident.block_type,
            recipe_id=recipe_id,
            success=improved,
            note=f"failure_rate {base_failure:.2f} → {fail_rate:.2f}",
        )
        if improved:
            result.recipe_kept = recipe_id
            result.notes = (
                f"kept {recipe_id}: failure_rate {base_failure:.2f} → {fail_rate:.2f}"
            )
            return result

    # exhausted — roll back
    await _safe_restore(xui, snap, snap_store)
    result.rolled_back = True
    result.notes = f"all {len(recipes)} recipes exhausted, rolled back to {snap.snapshot_id}"
    return result


async def _safe_restore(xui: XUIClient, snap: Snapshot, store: SnapshotStore) -> None:
    try:
        n = await restore_snapshot(xui, snap.snapshot_id, store=store)
        logger.info("rollback restored %d inbounds from %s", n, snap.snapshot_id)
    except Exception:
        logger.exception("CRITICAL: rollback failed for %s", snap.snapshot_id)


# ─── Manual rollback CLI hook ───────────────────────────────────────────────


async def rollback(snapshot_id: str, xui: XUIClient, *, store: SnapshotStore | None = None) -> int:
    return await restore_snapshot(xui, snapshot_id, store=store or SnapshotStore())


__all__ = [
    "ApplyConfig",
    "ApplyResult",
    "apply_incident",
    "order_recipes_for_incident",
    "rollback",
]


_ = utcnow  # re-export hook so callers can import a single source for time
