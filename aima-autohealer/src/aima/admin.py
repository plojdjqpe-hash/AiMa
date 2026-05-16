"""Admin / dashboard endpoints for AIMA.

These read-only endpoints surface what the auto-healer has observed and
learned so an operator can answer questions like:

    * how many probes did we run today, what's the success rate?
    * which (ASN × block_type × recipe) combinations have we tried, and
      how confident are we in each outcome?
    * what's the overall "training progress" — are we close to a useful
      verdict catalog or still in early data collection?

The endpoints are mounted under ``/aima/admin/...`` from
``integration/xservis_loader.py`` so they live next to ``/aima/health``,
``/aima/incidents``, etc.

No authentication is enforced at this layer — protect it via the host
backend's existing admin gate (the same one guarding ``/api/admin/*``).
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta

from fastapi import APIRouter

from .store import Store
from .types import utcnow

# Number of distinct (asn, block_type) combinations we'd want to see at least
# one outcome for before considering the catalog "trained" at 100%. Real
# production deployments will want this much higher; this is a sane default
# for the prototype.
TRAINING_COVERAGE_TARGET = 32
# Per-row sample-size threshold above which a learned_rules row is considered
# "confidently learned" (success_count + failure_count ≥ this many).
ROW_CONFIDENCE_SAMPLES = 10


def _row_get_int(row: sqlite3.Row, key: str, default: int = 0) -> int:
    """Safe row[key] returning an int, tolerant of legacy DBs missing the column."""

    try:
        v = row[key]
    except (IndexError, KeyError):
        return default
    if v is None:
        return default
    return int(v)


def _row_to_learning_entry(row: sqlite3.Row) -> dict:
    success = int(row["success_count"] or 0)
    failure = int(row["failure_count"] or 0)
    observed = _row_get_int(row, "observed_count", 0)
    total = success + failure
    success_rate = success / total if total > 0 else 0.0
    asn_raw = int(row["asn"]) if row["asn"] is not None else -1
    asn: int | None = None if asn_raw == -1 else asn_raw
    return {
        "asn": asn,
        "block_type": row["block_type"],
        "recipe_id": row["recipe_id"],
        "success_count": success,
        "failure_count": failure,
        "observed_count": observed,
        "total_attempts": total,
        "success_rate": round(success_rate, 4),
        # 0..1 confidence in this row alone (saturates at ROW_CONFIDENCE_SAMPLES)
        "confidence": round(min(total / ROW_CONFIDENCE_SAMPLES, 1.0), 4),
        "last_outcome_at": row["last_outcome_at"],
        "last_note": row["last_note"] or "",
    }


def _query_all(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    cur = conn.cursor()
    try:
        return cur.execute(sql, args).fetchall()
    finally:
        cur.close()


def _query_scalar(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> int:
    cur = conn.cursor()
    try:
        row = cur.execute(sql, args).fetchone()
        if row is None:
            return 0
        return int(row[0] or 0)
    finally:
        cur.close()


def build_admin_router(store_factory: Callable[[], Store]) -> APIRouter:
    """Build read-only admin router. Pure functions, no scheduler hooks."""

    router = APIRouter()

    @router.get("/stats")
    async def stats() -> dict:
        """High-level counters for the dashboard top-bar."""

        store = store_factory()
        conn = store._conn  # noqa: SLF001 — internal handle by design
        cutoff_24h = (utcnow() - timedelta(hours=24)).isoformat()

        total_reports = _query_scalar(conn, "SELECT COUNT(*) FROM reports")
        recent_reports = _query_scalar(
            conn, "SELECT COUNT(*) FROM reports WHERE started_at >= ?", (cutoff_24h,)
        )
        successful_recent = _query_scalar(
            conn,
            "SELECT COUNT(*) FROM reports WHERE started_at >= ? AND success = 1",
            (cutoff_24h,),
        )
        success_rate_24h = (successful_recent / recent_reports) if recent_reports else 0.0

        return {
            "now": utcnow().isoformat(),
            "profiles": _query_scalar(conn, "SELECT COUNT(*) FROM profiles"),
            "reports_total": total_reports,
            "reports_24h": recent_reports,
            "success_rate_24h": round(success_rate_24h, 4),
            "incidents_total": _query_scalar(conn, "SELECT COUNT(*) FROM incidents"),
            "incidents_open_60min": _query_scalar(
                conn,
                "SELECT COUNT(*) FROM incidents WHERE last_seen_at >= ?",
                ((utcnow() - timedelta(minutes=60)).isoformat(),),
            ),
            "learning_rows": _query_scalar(conn, "SELECT COUNT(*) FROM learned_rules"),
            "vantages_seen": _query_scalar(
                conn, "SELECT COUNT(DISTINCT vantage) FROM reports"
            ),
            "asns_seen": _query_scalar(
                conn, "SELECT COUNT(DISTINCT asn) FROM reports WHERE asn IS NOT NULL"
            ),
        }

    @router.get("/learning")
    async def learning(*, min_attempts: int = 0, limit: int = 500) -> dict:
        """Full learned-rules table with success rate per row.

        Use ``min_attempts`` to filter out rows that haven't accumulated enough
        outcomes yet. Default 0 returns everything we know.
        """

        store = store_factory()
        rows = _query_all(
            store._conn,  # noqa: SLF001
            """
            SELECT *
            FROM learned_rules
            WHERE (success_count + failure_count) >= ?
            ORDER BY (success_count + failure_count) DESC,
                     last_outcome_at DESC
            LIMIT ?
            """,
            (min_attempts, max(1, min(limit, 5000))),
        )
        entries = [_row_to_learning_entry(r) for r in rows]
        return {
            "min_attempts": min_attempts,
            "count": len(entries),
            "rows": entries,
        }

    @router.get("/learning/progress")
    async def learning_progress() -> dict:
        """Overall training progress estimate.

        ``percent_complete`` blends three observable signals:

          * coverage   — distinct (ASN, block_type) combinations we've seen
                          relative to ``TRAINING_COVERAGE_TARGET``.
          * confidence — average per-row confidence across all learned rows.
          * recipe_diversity — distinct recipes that have at least one outcome.

        It's deliberately conservative: an empty DB returns ``0%``, fully
        explored target with ≥ ``ROW_CONFIDENCE_SAMPLES`` per row returns
        ``100%``. Numbers are rounded to 2 decimals so the UI doesn't flicker.
        """

        store = store_factory()
        conn = store._conn  # noqa: SLF001
        rows = _query_all(conn, "SELECT * FROM learned_rules")

        total_rows = len(rows)
        confidence_sum = 0.0
        coverage_pairs: set[tuple[int, str]] = set()
        recipes_with_outcomes: set[str] = set()
        recipes_observed: set[str] = set()
        confident_rows = 0
        observation_rows = 0

        for r in rows:
            success = int(r["success_count"] or 0)
            failure = int(r["failure_count"] or 0)
            observed = _row_get_int(r, "observed_count", 0)
            total = success + failure
            block_type = str(r["block_type"])
            recipe_id = str(r["recipe_id"])
            asn_int = int(r["asn"])
            if total == 0 and observed == 0:
                continue
            # weighted: real outcomes worth more than passive observations
            weight = min((total + observed * 0.25) / ROW_CONFIDENCE_SAMPLES, 1.0)
            confidence_sum += weight
            coverage_pairs.add((asn_int, block_type))
            if total > 0:
                recipes_with_outcomes.add(recipe_id)
                if total >= ROW_CONFIDENCE_SAMPLES:
                    confident_rows += 1
            if observed > 0:
                recipes_observed.add(recipe_id)
                observation_rows += 1

        avg_confidence = confidence_sum / total_rows if total_rows else 0.0
        coverage = min(len(coverage_pairs) / TRAINING_COVERAGE_TARGET, 1.0)
        # Recipe diversity caps at the number of distinct recipes we've seen
        # so far; treat 8+ as fully diverse for prototype purposes.
        all_recipes_seen = recipes_with_outcomes | recipes_observed
        recipe_diversity = min(len(all_recipes_seen) / 8.0, 1.0)
        # Equal-weight blend.
        percent_complete = round(
            (avg_confidence + coverage + recipe_diversity) / 3.0 * 100.0, 2
        )

        return {
            "percent_complete": percent_complete,
            "coverage_pairs_seen": len(coverage_pairs),
            "coverage_target": TRAINING_COVERAGE_TARGET,
            "average_row_confidence": round(avg_confidence, 4),
            "confident_rows": confident_rows,
            "observation_rows": observation_rows,
            "total_rows": total_rows,
            "recipe_diversity": round(recipe_diversity, 4),
            "recipes_with_outcomes": sorted(recipes_with_outcomes),
            "recipes_observed": sorted(recipes_observed),
        }

    @router.get("/telemetry/summary")
    async def telemetry_summary(*, hours: int = 24) -> dict:
        """Per-profile + per-block-type rollup over the last ``hours``."""

        store = store_factory()
        conn = store._conn  # noqa: SLF001
        cutoff = (utcnow() - timedelta(hours=max(1, min(hours, 7 * 24)))).isoformat()

        rows = _query_all(
            conn,
            """
            SELECT profile_id,
                   vantage,
                   block_type,
                   success,
                   rtt_ms,
                   handshake_ms,
                   throughput_kbps,
                   started_at
            FROM reports
            WHERE started_at >= ?
            ORDER BY started_at
            """,
            (cutoff,),
        )

        by_profile: dict[str, dict] = {}
        block_counter: Counter[str] = Counter()
        vantage_counter: Counter[str] = Counter()
        latest_started_at: datetime | None = None

        for r in rows:
            block_counter[r["block_type"]] += 1
            vantage_counter[r["vantage"]] += 1
            try:
                started = datetime.fromisoformat(r["started_at"])
            except (TypeError, ValueError):
                started = None
            if started is not None and (
                latest_started_at is None or started > latest_started_at
            ):
                latest_started_at = started

            entry = by_profile.setdefault(
                r["profile_id"],
                {
                    "profile_id": r["profile_id"],
                    "samples": 0,
                    "successes": 0,
                    "rtt_ms_sum": 0.0,
                    "rtt_ms_count": 0,
                    "handshake_ms_sum": 0.0,
                    "handshake_ms_count": 0,
                    "throughput_kbps_sum": 0.0,
                    "throughput_kbps_count": 0,
                    "block_types": Counter(),
                },
            )
            entry["samples"] += 1
            entry["successes"] += 1 if r["success"] else 0
            entry["block_types"][r["block_type"]] += 1
            for key in ("rtt_ms", "handshake_ms", "throughput_kbps"):
                v = r[key]
                if v is None:
                    continue
                entry[f"{key}_sum"] += float(v)
                entry[f"{key}_count"] += 1

        def _avg(entry: dict, sum_key: str, count_key: str) -> float | None:
            c = entry[count_key]
            return round(entry[sum_key] / c, 2) if c else None

        profiles_out: list[dict] = []
        for pid, e in sorted(by_profile.items()):
            samples = e["samples"]
            success_rate = e["successes"] / samples if samples else 0.0

            profiles_out.append(
                {
                    "profile_id": pid,
                    "samples": samples,
                    "successes": e["successes"],
                    "success_rate": round(success_rate, 4),
                    "avg_rtt_ms": _avg(e, "rtt_ms_sum", "rtt_ms_count"),
                    "avg_handshake_ms": _avg(e, "handshake_ms_sum", "handshake_ms_count"),
                    "avg_throughput_kbps": _avg(
                        e, "throughput_kbps_sum", "throughput_kbps_count"
                    ),
                    "block_types": dict(e["block_types"].most_common()),
                }
            )

        return {
            "since": cutoff,
            "now": utcnow().isoformat(),
            "latest_report_at": (
                latest_started_at.isoformat() if latest_started_at is not None else None
            ),
            "total_reports": len(rows),
            "by_block_type": dict(block_counter.most_common()),
            "by_vantage": dict(vantage_counter.most_common()),
            "profiles": profiles_out,
        }

    return router


__all__ = ["build_admin_router", "TRAINING_COVERAGE_TARGET", "ROW_CONFIDENCE_SAMPLES"]
