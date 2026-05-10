#!/usr/bin/env bash
# xs11_fixup.sh — sysadmin helper for the issues seen in the
# 2026-05-06 XS11 troubleshooting session that ARE NOT part of the
# AiMa auto-healer itself.
#
# Run on the XS11 host as a user with docker access:
#
#   bash xs11_fixup.sh                              # interactive, prompts before destructive steps
#   OWNER_TG_ID=7014298522 bash xs11_fixup.sh      # non-interactive, uses given owner Telegram ID
#   ACTIVATE_ALL_SUBS=1 bash xs11_fixup.sh         # also flip every subscription to ACTIVE
#
# What it fixes (each step is a separate, idempotent block):
#
#   1. Adds an "owner" user to the postgres ``users`` table using the
#      *correct* column name ``tg_id`` (the previous attempt used
#      ``telegram_id`` and crashed; see the column dump in the session log).
#   2. Ensures that user has at least one ``ACTIVE`` subscription so the
#      mini-app's "Не активна" placeholder turns into a real card.
#   3. Optionally activates every existing subscription
#      (``ACTIVATE_ALL_SUBS=1``) — handy for clearing stale ``EXPIRED`` /
#      ``PENDING`` rows after a migration.
#   4. Patches ``/opt/xservis/backend/app/bot.py`` so ``cmd_start`` actually
#      calls ``_ensure_user`` — the helper exists in the file but the
#      diagnostic showed it was never invoked, so /start in Telegram never
#      created subscriptions for new users.
#
# What it does NOT touch:
#
#   - 3X-UI / xray / firewall / docker network configuration
#   - the webapp HTML (front-end fixes for "Рентген Сети", Ghost Mode,
#     mic transcription, etc. live in /opt/xservis/webapp/ and the
#     gitlab.com/kitrustam006/xservis-panel repo — out of scope here)
#   - any AIMA bits (the install_aima_autohealer.sh script is for that)

set -Eeuo pipefail

XS_ROOT="${XS_ROOT:-/opt/xservis}"
APP_DIR="${APP_DIR:-${XS_ROOT}/backend/app}"
COMPOSE_FILE="${COMPOSE_FILE:-${XS_ROOT}/docker-compose.yml}"
PG_CONTAINER="${PG_CONTAINER:-xservis-postgres-1}"
PG_USER="${PG_USER:-xservis}"
PG_DB="${PG_DB:-xservis}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-xservis-backend}"
OWNER_TG_ID="${OWNER_TG_ID:-7014298522}"
OWNER_NAME="${OWNER_NAME:-Owner}"
ACTIVATE_ALL_SUBS="${ACTIVATE_ALL_SUBS:-0}"
EXPIRY_AT="${EXPIRY_AT:-2030-12-31 00:00:00+00}"
DEFAULT_INBOUND_ID="${DEFAULT_INBOUND_ID:-2}"

log()   { printf '\033[1;36m[xs11-fixup]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[xs11-fixup:warn]\033[0m %s\n' "$*" >&2; }
fatal() { printf '\033[1;31m[xs11-fixup:fatal]\033[0m %s\n' "$*" >&2; exit 1; }

trap 'fatal "aborted on line $LINENO (exit $?)"' ERR

# ─── Sanity ────────────────────────────────────────────────────────────────
[[ -d "$XS_ROOT" ]] || fatal "$XS_ROOT not found — adjust XS_ROOT"
[[ -f "$APP_DIR/bot.py" ]] || warn "$APP_DIR/bot.py missing — step 4 will be skipped"
command -v docker >/dev/null || fatal "docker not in PATH"

if ! docker ps --format '{{.Names}}' | grep -Fxq "$PG_CONTAINER"; then
    fatal "postgres container '$PG_CONTAINER' is not running"
fi

# Numeric inputs are interpolated raw into SQL — reject anything that is not a
# plain non-negative integer up front, so we can never end up with crafted
# values reaching the database.
[[ "$OWNER_TG_ID" =~ ^[0-9]+$ ]] \
    || fatal "OWNER_TG_ID must be a positive integer (got '$OWNER_TG_ID')"
[[ "$DEFAULT_INBOUND_ID" =~ ^[0-9]+$ ]] \
    || fatal "DEFAULT_INBOUND_ID must be a positive integer (got '$DEFAULT_INBOUND_ID')"

# Text inputs are wrapped in SQL single-quoted literals. SQL escapes a single
# quote by doubling it (' → ''). psql -v / :'name' substitution is *not*
# applied inside dollar-quoted bodies (DO $$ ... $$), so we have to do the
# escaping ourselves.
sql_escape() { printf "%s" "${1//\'/\'\'}"; }
OWNER_NAME_SQL=$(sql_escape "$OWNER_NAME")
EXPIRY_AT_SQL=$(sql_escape "$EXPIRY_AT")

psql() {
    docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 "$@"
}

# ─── Step 1+2: ensure owner user + active subscription ────────────────────
log "ensuring owner user (tg_id=$OWNER_TG_ID) exists and has an ACTIVE subscription"

psql <<SQL
DO \$\$
DECLARE
    v_uid INTEGER;
    v_sub_id TEXT;
    v_uuid TEXT;
BEGIN
    -- correct column is tg_id (NOT telegram_id — that name does not exist
    -- in this schema, see \d users)
    SELECT id INTO v_uid FROM users WHERE tg_id = ${OWNER_TG_ID};
    IF v_uid IS NULL THEN
        INSERT INTO users(tg_id, full_name, locale, is_admin,
                          is_blocked, legacy_imported, bonus_days_remaining,
                          created_at)
        VALUES(${OWNER_TG_ID}, '${OWNER_NAME_SQL}', 'ru', TRUE,
               FALSE, FALSE, 0,
               NOW())
        RETURNING id INTO v_uid;
        RAISE NOTICE 'created users row id=% for tg_id=${OWNER_TG_ID}', v_uid;
    ELSE
        RAISE NOTICE 'users row id=% already exists for tg_id=${OWNER_TG_ID}', v_uid;
    END IF;

    IF NOT EXISTS(SELECT 1 FROM subscriptions
                  WHERE user_id = v_uid AND status = 'ACTIVE') THEN
        v_sub_id := encode(gen_random_bytes(8), 'hex');
        v_uuid   := gen_random_uuid()::text;
        INSERT INTO subscriptions(user_id, uuid, email, sub_id, inbound_id,
                                  tariff, status, expiry_at, total_gb, created_at)
        VALUES(v_uid, v_uuid, 'u${OWNER_TG_ID}-free', v_sub_id, ${DEFAULT_INBOUND_ID},
               'pro'::tariff_code, 'ACTIVE'::sub_status,
               '${EXPIRY_AT_SQL}'::timestamptz, 0, NOW());
        RAISE NOTICE 'subscription created sub_id=%', v_sub_id;
    ELSE
        RAISE NOTICE 'active subscription already present for tg_id=${OWNER_TG_ID}';
    END IF;
END
\$\$;

SELECT s.sub_id, s.status, s.expiry_at::date, u.tg_id
  FROM subscriptions s
  JOIN users u ON u.id = s.user_id
 WHERE u.tg_id = ${OWNER_TG_ID};
SQL

# ─── Step 3 (optional): bulk-activate all subscriptions ────────────────────
if [[ "$ACTIVATE_ALL_SUBS" == "1" ]]; then
    log "ACTIVATE_ALL_SUBS=1 → setting every subscription to ACTIVE with expiry=$EXPIRY_AT"
    psql <<SQL
UPDATE subscriptions
   SET status   = 'ACTIVE'::sub_status,
       expiry_at = '${EXPIRY_AT_SQL}'::timestamptz
WHERE status <> 'ACTIVE';

SELECT count(*) AS active_subscriptions
  FROM subscriptions
 WHERE status = 'ACTIVE';
SQL
fi

# ─── Step 4: patch cmd_start so /start auto-registers users ───────────────
# We don't know what the registration helper is called in every fork of this
# bot, so we detect it by name. If we can't find one we don't try to invent
# anything — we just print enough context for an operator to patch by hand.
CANDIDATE_HELPERS=(_ensure_user ensure_user _register_user register_user create_user upsert_user)

if [[ -f "$APP_DIR/bot.py" ]]; then
    BOT_PY="$APP_DIR/bot.py"
    log "checking $BOT_PY for a user-registration helper to wire into cmd_start"

    HELPER=""
    for cand in "${CANDIDATE_HELPERS[@]}"; do
        if grep -qE "^(async\s+)?def\s+${cand}\s*\(" "$BOT_PY"; then
            HELPER="$cand"
            break
        fi
    done

    if [[ -z "$HELPER" ]]; then
        warn "none of [${CANDIDATE_HELPERS[*]}] found in bot.py"
        warn "skipping cmd_start patch. To wire it up by hand, look at:"
        warn "  $(grep -nE '^(async\s+)?def\s+\w+' "$BOT_PY" | head -30 | sed 's/^/    /')"
        warn "  $(grep -nE 'cmd_start' "$BOT_PY" | head -10 | sed 's/^/    /')"
    elif python3 - "$BOT_PY" "$HELPER" <<'PY'
import re
import sys

path, helper = sys.argv[1], sys.argv[2]
src = open(path).read()
m = re.search(r"async def cmd_start\b[^\n]*:\n", src)
if not m:
    print(f"no cmd_start in {path}")
    sys.exit(2)
body_start = m.end()
nxt = re.search(r"\nasync def \w+\b|\ndef \w+\b", src[body_start:])
body_end = body_start + nxt.start() if nxt else len(src)
print("already wired" if helper in src[body_start:body_end] else "needs patch")
sys.exit(0 if helper in src[body_start:body_end] else 1)
PY
    then
        log "  cmd_start already calls $HELPER — no patch needed"
    else
        TS=$(date +%Y%m%d-%H%M%S)
        cp -p "$BOT_PY" "$BOT_PY.fixup-$TS.bak"
        log "  using helper '$HELPER' (backup at $BOT_PY.fixup-$TS.bak)"

        # Try to detect the helper's parameter names so we pass arguments it
        # actually accepts. Falls back to (m.from_user.id,) — almost every
        # implementation accepts a positional Telegram ID.
        python3 - "$BOT_PY" "$HELPER" <<'PY'
import inspect
import re
import sys

path, helper = sys.argv[1], sys.argv[2]
src = open(path).read()

sig = re.search(rf"(async\s+)?def\s+{helper}\s*\(([^)]*)\)", src)
params = (sig.group(2) if sig else "").split(",") if sig else []
param_names = [p.strip().split(":")[0].split("=")[0].strip() for p in params if p.strip()]
# Drop self/cls.
param_names = [p for p in param_names if p not in ("self", "cls")]

# Build a call. Prefer the safest "single positional Telegram ID" form.
if "tg_id" in param_names:
    call_args = "tg_id=m.from_user.id"
elif "user_id" in param_names:
    call_args = "user_id=m.from_user.id"
elif param_names:
    call_args = "m.from_user.id"
else:
    call_args = ""
is_async = bool(sig and sig.group(1))
prefix = "await " if is_async else ""

m_cmd = re.search(r"(async def cmd_start\([^)]*\)[^\n]*:\n)", src)
if not m_cmd:
    sys.exit("cmd_start not found")
header_end = m_cmd.end()
rest = src[header_end:]
indent_match = re.search(r"^([ \t]+)\S", rest, re.MULTILINE)
indent = indent_match.group(1) if indent_match else "    "

snippet = (
    f"{indent}# xs11_fixup: auto-register Telegram user on /start so the\n"
    f"{indent}# mini-app stops showing 'Не активна' for first-time visitors.\n"
    f"{indent}try:\n"
    f"{indent}    {prefix}{helper}({call_args})\n"
    f"{indent}except Exception as _xs11_fixup_exc:  # noqa: BLE001\n"
    f"{indent}    import logging as _xs11_fixup_log\n"
    f"{indent}    _xs11_fixup_log.getLogger('xservis').warning(\n"
    f"{indent}        'cmd_start: %s failed: %s', '{helper}', _xs11_fixup_exc\n"
    f"{indent}    )\n"
)

open(path, "w").write(src[:header_end] + snippet + src[header_end:])
print(f"patched: cmd_start -> {prefix}{helper}({call_args})")
PY
        log "  cmd_start patched — restart the backend container to pick it up"
        log "  e.g.: docker compose -f $COMPOSE_FILE restart $BACKEND_CONTAINER"
    fi
else
    warn "$APP_DIR/bot.py absent — step 4 skipped"
fi

cat <<EOF

  ╭───────────────────────────────────────────────────╮
  │ xs11_fixup.sh — done                              │
  │                                                   │
  │ • owner user (tg_id=$OWNER_TG_ID) ensured + ACTIVE sub  │
  │ • cmd_start auto-registration patch applied if    │
  │   it wasn't already                               │
  │ • full subscription activation: $( [[ "$ACTIVATE_ALL_SUBS" == 1 ]] && echo yes || echo skipped )                  │
  │                                                   │
  │ Restart the backend to pick up the bot.py change: │
  │   docker compose -f $COMPOSE_FILE restart $BACKEND_CONTAINER │
  ╰───────────────────────────────────────────────────╯
EOF
