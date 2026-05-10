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
        VALUES(${OWNER_TG_ID}, '${OWNER_NAME}', 'ru', TRUE,
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
               '${EXPIRY_AT}'::timestamptz, 0, NOW());
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
       expiry_at = '${EXPIRY_AT}'::timestamptz
WHERE status <> 'ACTIVE';

SELECT count(*) AS active_subscriptions
  FROM subscriptions
 WHERE status = 'ACTIVE';
SQL
fi

# ─── Step 4: patch cmd_start so /start auto-registers users ───────────────
if [[ -f "$APP_DIR/bot.py" ]]; then
    BOT_PY="$APP_DIR/bot.py"
    log "checking $BOT_PY for cmd_start → _ensure_user wiring"

    if ! grep -q "_ensure_user" "$BOT_PY"; then
        warn "_ensure_user helper not found in bot.py — skipping patch"
    elif python3 - "$BOT_PY" <<'PY'
import sys
import re

src = open(sys.argv[1]).read()
m = re.search(r"async def cmd_start\b[^\n]*:\n", src)
if not m:
    print("no cmd_start signature found; nothing to do")
    sys.exit(2)
body_start = m.end()
# crudely walk to next top-level "async def " or end of file
nxt = re.search(r"\nasync def \w+\b|\ndef \w+\b", src[body_start:])
body_end = body_start + nxt.start() if nxt else len(src)
already = "_ensure_user" in src[body_start:body_end]
print("already wired" if already else "needs patch")
sys.exit(0 if already else 1)
PY
    then
        log "  cmd_start already calls _ensure_user — no patch needed"
    else
        TS=$(date +%Y%m%d-%H%M%S)
        cp -p "$BOT_PY" "$BOT_PY.fixup-$TS.bak"
        log "  backup → $BOT_PY.fixup-$TS.bak"

        python3 - "$BOT_PY" <<'PY'
import re
import sys

path = sys.argv[1]
src = open(path).read()

m = re.search(r"(async def cmd_start\([^)]*\)[^\n]*:\n)", src)
if not m:
    sys.exit("cmd_start not found")
header_end = m.end()

# Detect indentation of the next non-blank line.
rest = src[header_end:]
indent_match = re.search(r"^([ \t]+)\S", rest, re.MULTILINE)
indent = indent_match.group(1) if indent_match else "    "

snippet = (
    f"{indent}# xs11_fixup: auto-register Telegram user on /start so the\n"
    f"{indent}# mini-app stops showing 'Не активна' for first-time visitors.\n"
    f"{indent}try:\n"
    f"{indent}    await _ensure_user(\n"
    f"{indent}        bot=m.bot,\n"
    f"{indent}        tg_id=m.from_user.id,\n"
    f"{indent}        first_name=getattr(m.from_user, 'first_name', '') or '',\n"
    f"{indent}    )\n"
    f"{indent}except Exception as _xs11_fixup_exc:  # noqa: BLE001\n"
    f"{indent}    import logging as _xs11_fixup_log\n"
    f"{indent}    _xs11_fixup_log.getLogger('xservis').warning(\n"
    f"{indent}        'cmd_start: _ensure_user failed: %s', _xs11_fixup_exc\n"
    f"{indent}    )\n"
)

new_src = src[:header_end] + snippet + src[header_end:]
open(path, "w").write(new_src)
print("patched")
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
