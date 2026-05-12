"""SQLite-backed persistence for probe reports, profiles, and incidents."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .types import (
    BlockType,
    Incident,
    IncidentSeverity,
    ProbeProfile,
    ProbeReport,
    TransportKind,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    sni TEXT,
    expected_status INTEGER,
    timeout_seconds REAL,
    extra_json TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    vantage TEXT NOT NULL,
    asn INTEGER,
    provider TEXT,
    region TEXT,
    started_at TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    success INTEGER NOT NULL,
    block_type TEXT NOT NULL,
    rtt_ms REAL,
    handshake_ms REAL,
    throughput_kbps REAL,
    error TEXT,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS reports_profile_started
    ON reports(profile_id, started_at);
CREATE INDEX IF NOT EXISTS reports_vantage_started
    ON reports(vantage, started_at);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    profile_id TEXT,
    vantage TEXT,
    block_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    started_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    failure_rate REAL NOT NULL,
    summary TEXT NOT NULL,
    suggested_recipes_json TEXT
);
CREATE INDEX IF NOT EXISTS incidents_open
    ON incidents(last_seen_at);

CREATE TABLE IF NOT EXISTS learned_rules (
    -- asn=-1 means "global / unspecified"; otherwise actual ASN integer.
    asn INTEGER NOT NULL DEFAULT -1,
    block_type TEXT NOT NULL,
    recipe_id TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_outcome_at TEXT NOT NULL,
    last_note TEXT,
    PRIMARY KEY (asn, block_type, recipe_id)
);
CREATE INDEX IF NOT EXISTS learned_rules_lookup
    ON learned_rules(block_type, asn);
"""

_GLOBAL_ASN = -1


class Store:
    """Tiny convenience wrapper around sqlite3 that speaks Pydantic models."""

    def __init__(self, db_path: str | Path = "aima.db") -> None:
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    def upsert_profile(self, p: ProbeProfile) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO profiles(id, label, kind, host, port, sni,
                                     expected_status, timeout_seconds, extra_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    label=excluded.label,
                    kind=excluded.kind,
                    host=excluded.host,
                    port=excluded.port,
                    sni=excluded.sni,
                    expected_status=excluded.expected_status,
                    timeout_seconds=excluded.timeout_seconds,
                    extra_json=excluded.extra_json
                """,
                (
                    p.id,
                    p.label,
                    p.kind.value,
                    p.host,
                    p.port,
                    p.sni,
                    p.expected_status,
                    p.timeout_seconds,
                    json.dumps(p.extra),
                ),
            )

    def list_profiles(self) -> list[ProbeProfile]:
        with self.cursor() as cur:
            rows = cur.execute("SELECT * FROM profiles ORDER BY id").fetchall()
        return [
            ProbeProfile(
                id=r["id"],
                label=r["label"],
                kind=TransportKind(r["kind"]),
                host=r["host"],
                port=r["port"],
                sni=r["sni"],
                expected_status=r["expected_status"],
                timeout_seconds=r["timeout_seconds"] or 6.0,
                extra=json.loads(r["extra_json"] or "{}"),
            )
            for r in rows
        ]

    def insert_report(self, r: ProbeReport) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reports(profile_id, vantage, asn, provider, region,
                                    started_at, duration_ms, success, block_type,
                                    rtt_ms, handshake_ms, throughput_kbps, error, raw_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.profile_id,
                    r.vantage,
                    r.asn,
                    r.provider,
                    r.region,
                    r.started_at.isoformat(),
                    r.duration_ms,
                    int(r.success),
                    r.block_type.value,
                    r.rtt_ms,
                    r.handshake_ms,
                    r.throughput_kbps,
                    r.error,
                    json.dumps(r.raw),
                ),
            )

    def insert_reports(self, reports: list[ProbeReport]) -> None:
        for r in reports:
            self.insert_report(r)

    def reports_since(
        self,
        since: datetime,
        *,
        profile_id: str | None = None,
        vantage: str | None = None,
    ) -> list[ProbeReport]:
        sql = "SELECT * FROM reports WHERE started_at >= ?"
        args: list[object] = [since.isoformat()]
        if profile_id is not None:
            sql += " AND profile_id = ?"
            args.append(profile_id)
        if vantage is not None:
            sql += " AND vantage = ?"
            args.append(vantage)
        sql += " ORDER BY started_at"
        with self.cursor() as cur:
            rows = cur.execute(sql, args).fetchall()
        return [
            ProbeReport(
                profile_id=r["profile_id"],
                vantage=r["vantage"],
                asn=r["asn"],
                provider=r["provider"],
                region=r["region"],
                started_at=datetime.fromisoformat(r["started_at"]),
                duration_ms=r["duration_ms"],
                success=bool(r["success"]),
                block_type=BlockType(r["block_type"]),
                rtt_ms=r["rtt_ms"],
                handshake_ms=r["handshake_ms"],
                throughput_kbps=r["throughput_kbps"],
                error=r["error"],
                raw=json.loads(r["raw_json"] or "{}"),
            )
            for r in rows
        ]

    def upsert_incident(self, inc: Incident) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO incidents(id, profile_id, vantage, block_type, severity,
                                      confidence, started_at, last_seen_at, sample_count,
                                      failure_rate, summary, suggested_recipes_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_seen_at=excluded.last_seen_at,
                    sample_count=excluded.sample_count,
                    failure_rate=excluded.failure_rate,
                    confidence=excluded.confidence,
                    severity=excluded.severity,
                    summary=excluded.summary,
                    suggested_recipes_json=excluded.suggested_recipes_json
                """,
                (
                    inc.id,
                    inc.profile_id,
                    inc.vantage,
                    inc.block_type.value,
                    inc.severity.value,
                    inc.confidence,
                    inc.started_at.isoformat(),
                    inc.last_seen_at.isoformat(),
                    inc.sample_count,
                    inc.failure_rate,
                    inc.summary,
                    json.dumps(inc.suggested_recipes),
                ),
            )

    # ─── Learned rules (per-ASN recipe success bookkeeping) ───────────────

    def record_recipe_outcome(
        self,
        *,
        asn: int | None,
        block_type: BlockType,
        recipe_id: str,
        success: bool,
        note: str = "",
    ) -> None:
        asn_key = _GLOBAL_ASN if asn is None else int(asn)
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO learned_rules
                    (asn, block_type, recipe_id, success_count, failure_count,
                     last_outcome_at, last_note)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asn, block_type, recipe_id) DO UPDATE SET
                    success_count = learned_rules.success_count + excluded.success_count,
                    failure_count = learned_rules.failure_count + excluded.failure_count,
                    last_outcome_at = excluded.last_outcome_at,
                    last_note = excluded.last_note
                """,
                (
                    asn_key,
                    block_type.value,
                    recipe_id,
                    1 if success else 0,
                    0 if success else 1,
                    datetime.now(UTC).isoformat(),
                    note,
                ),
            )

    def learned_priority_map(self) -> dict[tuple[int | None, BlockType, str], float]:
        """Returns score for each (asn, block_type, recipe) row.

        score = (success - failure) / (success + failure)  ∈ [-1..1]
        Higher = more preferred. Rows with no outcomes are omitted.
        """

        out: dict[tuple[int | None, BlockType, str], float] = {}
        with self.cursor() as cur:
            rows = cur.execute(
                "SELECT asn, block_type, recipe_id, success_count, failure_count "
                "FROM learned_rules"
            ).fetchall()
        for r in rows:
            total = (r["success_count"] or 0) + (r["failure_count"] or 0)
            if total == 0:
                continue
            score = (r["success_count"] - r["failure_count"]) / total
            asn_key: int | None = None if r["asn"] == _GLOBAL_ASN else int(r["asn"])
            out[(asn_key, BlockType(r["block_type"]), r["recipe_id"])] = score
        return out

    def incidents_recent(self, *, max_age_minutes: int = 60) -> list[Incident]:
        cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        with self.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM incidents WHERE last_seen_at >= ? ORDER BY last_seen_at DESC",
                (cutoff.isoformat(),),
            ).fetchall()
        return [
            Incident(
                id=r["id"],
                profile_id=r["profile_id"],
                vantage=r["vantage"],
                block_type=BlockType(r["block_type"]),
                severity=IncidentSeverity(r["severity"]),
                confidence=r["confidence"],
                started_at=datetime.fromisoformat(r["started_at"]),
                last_seen_at=datetime.fromisoformat(r["last_seen_at"]),
                sample_count=r["sample_count"],
                failure_rate=r["failure_rate"],
                summary=r["summary"],
                suggested_recipes=json.loads(r["suggested_recipes_json"] or "[]"),
            )
            for r in rows
        ]
