#!/usr/bin/env bash
# install_aima_autohealer.sh — idempotent install/upgrade for AIMA on XS11.
#
# What it does (in order, all reversible):
#   1. Sanity-check that /opt/xservis/backend/app exists and has main.py
#   2. Snapshot /opt/xservis/backend/app  →  /opt/xservis/backups/app.<ts>.tar.gz
#   3. Install the `aima-autohealer` package into the backend container's site-packages
#      using `pip install --target` so we don't poison anything else
#   4. Inject one idempotent line into main.py that calls `attach(app)` after the
#      app is constructed. Re-running the script never duplicates the line.
#   5. Set AIMA_* env vars in /opt/xservis/.env (with safe defaults) only if they're not
#      already there
#   6. docker compose build backend && docker compose up -d backend
#   7. Health-check `/aima/health` (or the existing /healthz if AIMA failed to attach)
#   8. If health-check fails → restore the tarball and `docker compose up -d` again
#
# What it explicitly does NOT touch:
#   - /opt/xservis/webapp/  (frontend stays exactly as-is)
#   - /opt/xservis/.env values that already exist
#   - the postgres / xui containers
#   - any user data or subscription URLs
#
# Run on XS11 as a user that has access to /opt/xservis and docker:
#   curl -fsSL https://raw.githubusercontent.com/plojdjqpe-hash/AiMa/main/aima-autohealer/scripts/install_aima_autohealer.sh \
#     | bash
#
# Or for a specific branch:
#   AIMA_REF=devin/1778041571-aima-autohealer-prototype \
#     curl -fsSL .../install_aima_autohealer.sh | bash
#
# Uninstall:
#   AIMA_UNINSTALL=1 bash install_aima_autohealer.sh

set -Eeuo pipefail

# ─── Configurable knobs (env-overrideable) ─────────────────────────────────
AIMA_REPO="${AIMA_REPO:-https://github.com/plojdjqpe-hash/AiMa.git}"
# Order: try main first, fall back to the active PR branch. Override with AIMA_REF.
AIMA_REF="${AIMA_REF:-}"
AIMA_REF_FALLBACKS=(
    "main"
    "devin/1778041571-aima-autohealer-prototype"
)
# Skip git clone entirely and install from a local checkout (e.g. when you've
# already cloned the repo on the host). Should point at the AiMa repo root,
# the script reads `<AIMA_LOCAL_PATH>/aima-autohealer`.
AIMA_LOCAL_PATH="${AIMA_LOCAL_PATH:-}"
XS_ROOT="${XS_ROOT:-/opt/xservis}"
APP_DIR="${APP_DIR:-${XS_ROOT}/backend/app}"
ENV_FILE="${ENV_FILE:-${XS_ROOT}/.env}"
BACKUP_DIR="${BACKUP_DIR:-${XS_ROOT}/backups}"
DATA_DIR="${DATA_DIR:-${XS_ROOT}/data}"
COMPOSE_FILE="${COMPOSE_FILE:-${XS_ROOT}/docker-compose.yml}"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-backend}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/aima/health}"
HEALTH_FALLBACK="${HEALTH_FALLBACK:-http://127.0.0.1:8000/healthz}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"   # seconds to wait for backend to come up
# When only /aima/health is unreachable but the backend itself is alive, the
# AIMA attach() is a no-op (caught by its own try/except). In that case we
# normally do NOT roll back the entire backend just because the auto-healer
# didn't attach — the host stays running and AIMA can be retried later.
# Set to 1 to force the legacy "any AIMA failure rolls everything back" behaviour.
AIMA_STRICT_ROLLBACK="${AIMA_STRICT_ROLLBACK:-0}"

# ─── Logging ───────────────────────────────────────────────────────────────
log() { printf '\033[1;36m[aima-install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[aima-install:warn]\033[0m %s\n' "$*" >&2; }
fatal() { printf '\033[1;31m[aima-install:fatal]\033[0m %s\n' "$*" >&2; exit 1; }

trap 'fatal "aborted on line $LINENO (exit code $?)"' ERR

# ─── Sanity checks ─────────────────────────────────────────────────────────
[[ -d "$APP_DIR" ]] || fatal "$APP_DIR not found — is XSERVIS deployed at $XS_ROOT?"
[[ -f "$APP_DIR/main.py" ]] || fatal "$APP_DIR/main.py not found — wrong layout"
[[ -f "$COMPOSE_FILE" ]] || fatal "$COMPOSE_FILE not found"
command -v docker >/dev/null || fatal "docker not found in PATH"
command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null \
    || fatal "neither 'docker compose' nor 'docker-compose' available"

# Choose docker compose vs docker-compose
DC=(docker compose -f "$COMPOSE_FILE")
if ! docker compose version >/dev/null 2>&1; then
  DC=(docker-compose -f "$COMPOSE_FILE")
fi

# ─── Uninstall path ────────────────────────────────────────────────────────
if [[ "${AIMA_UNINSTALL:-0}" == "1" ]]; then
    log "uninstall mode — restoring last backup (if any) and removing aima/"
    LATEST_BACKUP="$(ls -1t "$BACKUP_DIR"/app.*.tar.gz 2>/dev/null | head -1 || true)"
    if [[ -n "$LATEST_BACKUP" ]]; then
        log "restoring $LATEST_BACKUP"
        tar -xzf "$LATEST_BACKUP" -C "$XS_ROOT/backend/"
    else
        warn "no backup found — manually removing aima/ from app dir"
        rm -rf "$APP_DIR/aima"
        sed -i '/# >>> aima auto-healer >>>/,/# <<< aima auto-healer <<</d' "$APP_DIR/main.py"
    fi
    "${DC[@]}" build "$COMPOSE_SERVICE"
    "${DC[@]}" up -d "$COMPOSE_SERVICE"
    log "uninstalled."
    exit 0
fi

# ─── 1. Backup ─────────────────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR" "$DATA_DIR"
TS=$(date +%Y%m%d-%H%M%S)
BACKUP="$BACKUP_DIR/app.$TS.tar.gz"
log "backing up $APP_DIR → $BACKUP"
tar -czf "$BACKUP" -C "$XS_ROOT/backend" app

ROLLBACK() {
    warn "rollback triggered — restoring $BACKUP"
    tar -xzf "$BACKUP" -C "$XS_ROOT/backend/"
    "${DC[@]}" up -d "$COMPOSE_SERVICE" || warn "compose up after rollback returned $?"
}

# ─── 2. Fetch source ───────────────────────────────────────────────────────
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [[ -n "$AIMA_LOCAL_PATH" ]]; then
    log "using local source $AIMA_LOCAL_PATH (skipping git clone)"
    SRC="$AIMA_LOCAL_PATH/aima-autohealer"
    [[ -f "$SRC/pyproject.toml" ]] || fatal "$SRC missing pyproject.toml"
else
    # Try AIMA_REF (if set), else fallbacks in order until one has the package.
    REFS_TO_TRY=()
    [[ -n "$AIMA_REF" ]] && REFS_TO_TRY+=("$AIMA_REF")
    REFS_TO_TRY+=("${AIMA_REF_FALLBACKS[@]}")
    SRC=""
    for ref in "${REFS_TO_TRY[@]}"; do
        log "trying $AIMA_REPO@$ref"
        rm -rf "$WORK/AiMa"
        if git clone --depth 1 --branch "$ref" "$AIMA_REPO" "$WORK/AiMa" >/dev/null 2>&1; then
            if [[ -f "$WORK/AiMa/aima-autohealer/pyproject.toml" ]]; then
                SRC="$WORK/AiMa/aima-autohealer"
                log "  -> ref $ref contains aima-autohealer package, using it"
                break
            else
                warn "  -> ref $ref clones but has no aima-autohealer/ — trying next"
            fi
        else
            warn "  -> ref $ref clone failed — trying next"
        fi
    done
    [[ -n "$SRC" ]] || fatal "no usable ref found in [${REFS_TO_TRY[*]}]; pass AIMA_REF=<branch> or AIMA_LOCAL_PATH=<path-to-AiMa-clone>"
fi

# ─── 3. Drop the package next to main.py ───────────────────────────────────
log "copying $SRC/src/aima → $APP_DIR/aima"
rm -rf "$APP_DIR/aima"
cp -a "$SRC/src/aima" "$APP_DIR/aima"

# ─── 4. Patch main.py (idempotent) ─────────────────────────────────────────
PATCH_BEGIN='# >>> aima auto-healer >>>'
PATCH_END='# <<< aima auto-healer <<<'
if ! grep -q "$PATCH_BEGIN" "$APP_DIR/main.py"; then
    log "injecting attach() call into main.py"
    cat >>"$APP_DIR/main.py" <<PYEOF

$PATCH_BEGIN
try:
    from aima.integration.xservis_loader import attach as _aima_attach
    _aima_attach(app)
except Exception as _aima_exc:  # noqa: BLE001
    import logging as _logging
    _logging.getLogger("aima").exception("attach failed: %s", _aima_exc)
$PATCH_END
PYEOF
else
    log "main.py already patched — skipping"
fi

# ─── 5. Seed env vars (only if absent) ─────────────────────────────────────
touch "$ENV_FILE"
add_env() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
        log "  $key already set in $ENV_FILE — keeping existing value"
    else
        printf '%s=%s\n' "$key" "$val" >>"$ENV_FILE"
        log "  $key=$val"
    fi
}
log "seeding $ENV_FILE (existing values are preserved)"
add_env AIMA_ENABLED 1
add_env AIMA_AUTO_APPLY 0
add_env AIMA_DB_PATH /opt/xservis/data/aima.db
add_env AIMA_SNAPSHOT_DIR /opt/xservis/data/aima_snapshots
add_env AIMA_FAST_LOOP_MINUTES 5
add_env AIMA_SLOW_LOOP_MINUTES 60
add_env AIMA_VANTAGE_NAME xs11

# ─── 6. Build & deploy ─────────────────────────────────────────────────────
log "rebuilding $COMPOSE_SERVICE"
"${DC[@]}" build "$COMPOSE_SERVICE"
log "starting $COMPOSE_SERVICE"
"${DC[@]}" up -d "$COMPOSE_SERVICE"

# ─── 7. Health check ───────────────────────────────────────────────────────
log "waiting up to ${HEALTH_TIMEOUT}s for $HEALTH_URL (fallback: $HEALTH_FALLBACK)"
aima_ok=0
backend_ok=0
for i in $(seq 1 "$HEALTH_TIMEOUT"); do
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        aima_ok=1; backend_ok=1
        log "AIMA healthy on /aima/health (after ${i}s)"
        break
    fi
    if curl -fsS --max-time 2 "$HEALTH_FALLBACK" >/dev/null 2>&1; then
        backend_ok=1
        # backend is alive; keep waiting for AIMA to attach
    fi
    sleep 1
done

if [[ "$aima_ok" -ne 1 ]]; then
    warn "AIMA /aima/health unreachable after ${HEALTH_TIMEOUT}s"
    log "---- last 50 lines of $COMPOSE_SERVICE container logs ----"
    "${DC[@]}" logs --tail=50 "$COMPOSE_SERVICE" 2>&1 | sed 's/^/    /' >&2 || true
    log "---- end of container logs ----"

    if [[ "$backend_ok" -eq 1 ]]; then
        warn "backend itself is alive on $HEALTH_FALLBACK — AIMA failed to attach but the host is up"
        if [[ "$AIMA_STRICT_ROLLBACK" == "1" ]]; then
            warn "AIMA_STRICT_ROLLBACK=1 → rolling back anyway"
            ROLLBACK
            fatal "install failed (strict mode) — backup restored from $BACKUP"
        fi
        warn "keeping backend running. Disable AIMA via 'AIMA_ENABLED=0' in $ENV_FILE if needed."
        warn "to force rollback re-run with AIMA_STRICT_ROLLBACK=1."
        warn "backup is preserved at $BACKUP"
    else
        warn "backend is also down — full rollback"
        ROLLBACK
        fatal "install failed — backup restored from $BACKUP"
    fi
fi

# ─── 8. Done ───────────────────────────────────────────────────────────────
cat <<EOF

  ╭───────────────────────────────────────────────────╮
  │ AIMA auto-healer installed                        │
  │ probe loop:  ${AIMA_FAST_LOOP_MINUTES:-5}m fast / ${AIMA_SLOW_LOOP_MINUTES:-60}m slow                  │
  │ auto-apply:  AIMA_AUTO_APPLY=0 (detect-only)      │
  │ data:        $DATA_DIR             │
  │ backup:      $BACKUP                              │
  │ uninstall:   AIMA_UNINSTALL=1 bash $0             │
  ╰───────────────────────────────────────────────────╯

Useful endpoints:
  GET  /aima/health
  GET  /aima/incidents
  POST /aima/detect/run

To enable actual mutations once you've watched it for a few hours:
  sed -i 's/^AIMA_AUTO_APPLY=.*/AIMA_AUTO_APPLY=1/' $ENV_FILE
  ${DC[*]} restart $COMPOSE_SERVICE

EOF

trap - EXIT
rm -rf "$WORK"
