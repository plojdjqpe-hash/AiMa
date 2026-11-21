"""Atomic snapshot & restore of XUI state and sub-renderer overrides.

A snapshot bundle (`<id>.json` on disk) contains:
    {
      "snapshot_id": "<sha1[:12]>",
      "created_at":  "2026-05-06T03:42:00Z",
      "inbounds":    [ <full inbound dicts> ],
      "renderer_overrides": { ... },   # arbitrary key/value overrides we set
      "applied_recipes": [ <recipe ids that produced this state> ],
      "note": "human-readable reason"
    }

Snapshots live in `AIMA_SNAPSHOT_DIR` (defaults to `./snapshots/` relative to
the working dir) and are pruned by age + count. Restoring a snapshot does an
update_inbound() per inbound and re-applies overrides; it never deletes
inbounds the user added in the meantime.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .types import utcnow
from .xui_client import XUIClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Snapshot:
    snapshot_id: str
    created_at: str
    inbounds: list[dict]
    renderer_overrides: dict = field(default_factory=dict)
    applied_recipes: list[str] = field(default_factory=list)
    note: str = ""


def _snapshot_id(inbounds: list[dict], note: str) -> str:
    h = hashlib.sha1()
    h.update(note.encode())
    h.update(json.dumps(inbounds, sort_keys=True, default=str).encode())
    h.update(utcnow().isoformat().encode())
    return h.hexdigest()[:12]


# Fields the mutation recipes are allowed to change. A restore only puts these back, so
# clients added and traffic counted while a recipe was being tested are never wiped.
RESTORABLE_FIELDS = ("port", "listen", "enable", "streamSettings", "sniffing")

_SNAPSHOT_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class SnapshotStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.environ.get("AIMA_SNAPSHOT_DIR", "snapshots"))
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            # snapshots hold full inbounds: client UUIDs, REALITY private keys
            os.chmod(self.root, 0o700)
        except OSError:
            logger.warning("snapshot dir %s: could not restrict permissions", self.root)

    def path_for(self, snapshot_id: str) -> Path:
        if not _SNAPSHOT_ID_RE.fullmatch(snapshot_id or ""):
            raise ValueError(f"invalid snapshot id: {snapshot_id!r}")
        return self.root / f"{snapshot_id}.json"

    def write(self, snap: Snapshot) -> Path:
        p = self.path_for(snap.snapshot_id)
        # atomic + private: write to a 0600 temp file in the same dir, then rename
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".snap-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps(asdict(snap), indent=2, sort_keys=True))
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        logger.info("snapshot %s written → %s (%d inbounds)", snap.snapshot_id, p, len(snap.inbounds))
        return p

    def read(self, snapshot_id: str) -> Snapshot:
        raw = json.loads(self.path_for(snapshot_id).read_text())
        return Snapshot(**raw)

    def list_recent(self, *, limit: int = 20) -> list[Snapshot]:
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [Snapshot(**json.loads(p.read_text())) for p in files[:limit]]

    def prune(self, *, keep: int = 50, max_age_days: int = 14) -> int:
        """Remove old snapshots. Returns count removed."""

        cutoff = datetime.now() - timedelta(days=max_age_days)
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        removed = 0
        for p in files[keep:]:
            if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                p.unlink()
                removed += 1
        if removed:
            logger.info("snapshot prune removed %d", removed)
        return removed


async def take_snapshot(
    xui: XUIClient,
    *,
    note: str,
    applied_recipes: list[str] | None = None,
    renderer_overrides: dict | None = None,
    store: SnapshotStore | None = None,
) -> Snapshot:
    inbounds = await xui.list_inbounds()
    snap = Snapshot(
        snapshot_id=_snapshot_id(inbounds, note),
        created_at=utcnow().isoformat(),
        inbounds=inbounds,
        renderer_overrides=renderer_overrides or {},
        applied_recipes=applied_recipes or [],
        note=note,
    )
    (store or SnapshotStore()).write(snap)
    return snap


def merge_for_restore(current: dict, saved: dict) -> dict:
    """Current inbound with only the recipe-controlled fields taken from the snapshot."""

    merged = dict(current)
    for key in RESTORABLE_FIELDS:
        if key in saved:
            merged[key] = saved[key]
        else:
            merged.pop(key, None)
    return merged


async def restore_snapshot(
    xui: XUIClient,
    snapshot_id: str,
    *,
    store: SnapshotStore | None = None,
    inbound_ids: set[int] | None = None,
) -> int:
    """Restore inbounds from the snapshot. Returns count of inbounds restored.

    Only the fields recipes mutate (``RESTORABLE_FIELDS``) are put back onto the *current*
    inbound. Previously the whole stale object was pushed, which silently deleted every
    client added (and reset traffic counters) since the snapshot was taken.
    Inbounds that no longer exist, and inbounds added after the snapshot, are left alone.
    ``inbound_ids`` limits the restore to the given inbounds.
    """

    snap = (store or SnapshotStore()).read(snapshot_id)
    current = {int(ib.get("id", -1)): ib for ib in await xui.list_inbounds()}
    n = 0
    for saved in snap.inbounds:
        ib_id = int(saved.get("id", -1))
        if ib_id < 0 or (inbound_ids is not None and ib_id not in inbound_ids):
            continue
        live = current.get(ib_id)
        if live is None:
            logger.warning("restore_snapshot %s: inbound %d no longer exists, skipped", snapshot_id, ib_id)
            continue
        merged = merge_for_restore(live, saved)
        if merged == live:
            continue
        await xui.update_inbound(ib_id, merged)
        n += 1
    logger.info("restore_snapshot %s: restored %d inbounds", snapshot_id, n)
    return n
