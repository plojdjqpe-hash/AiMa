#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$PWD}"
cd "$ROOT"

TS="$(date +%Y%m%d-%H%M%S)"
mkdir -p .ai-token70/backups
mkdir -p .claude/commands

POLICY_FILE=".ai-token70/AUTO_TOKEN70_POLICY.md"

cat > "$POLICY_FILE" <<'EOF'
# AUTO TOKEN-70 / QUALITY SAFE MODE

Default behavior: always minimize token usage by ~70% while preserving output quality.

Core objective:
Produce the same useful result with fewer tokens by removing repetition, filler, excessive explanation, full-file dumps, and unnecessary context.

Mandatory response format:
[Логика/стратегия] — 1–2 предложения.
[Финальный результат] — code / diff / command / plan / text.
[Инструкция] — 1 строка.

Global rules:
- Do not repeat the user's request.
- Do not write introductions.
- Do not write generic disclaimers.
- Do not reveal chain-of-thought.
- Do not summarize files unless asked.
- Do not output full files unless strictly necessary.
- Prefer minimal patches, diffs, commands, and exact edits.
- Read only relevant files.
- Search narrowly before broad scans.
- Preserve existing architecture unless explicitly asked.
- Preserve quality over extreme compression.
- If compression risks correctness, use slightly more tokens and say why in one short line.
- Do not modify server configs, VPN configs, keys, secrets, or production settings without the exact phrase: "Подтверждаю изменение конфига".

For code tasks:
- First identify the smallest safe change.
- Output unified diff when possible.
- If creating a file, output only that file.
- If editing many files, list files first, then diffs.
- Do not add libraries unless required.
- Do not refactor unrelated code.
- Do not invent hidden requirements.

For debugging:
- Output: cause → proof → fix → check command.
- Use top-5 likely causes maximum.
- Do not paste long logs back.
- Quote only critical log lines.

For architecture:
- Maximum 7 points.
- Include tradeoffs only if they affect implementation.
- No theory.

For review:
- Use table: issue → risk → fix.
- Maximum 10 issues.
- Prioritize production-breaking defects.

For scripts:
- One copy-pasteable script.
- Idempotent when possible.
- Backup before changing files.
- Fail safely.
- Print exact next command.

For marketing:
- If carousel requested: exactly 10 slides.
- Slide 1 hook, 2 re-hook, 3 pain, 4–7 value, 8 insight, 9 steps, 10 CTA.
- Short, vivid, FOMO, one visual style.

Token budget:
- Normal answer: 700–1400 characters.
- Complex answer: only as long as needed.
- Plans: max 7 steps.
- Explanations: max 5 bullets.
- Code comments: minimal.
- Avoid duplicated command blocks.

Quality gate before final:
- Is the answer directly usable?
- Did it avoid unnecessary context?
- Did it preserve safety?
- Did it avoid changing configs/secrets without permission?
- Did it provide the shortest complete result?
EOF

AUTO_BLOCK="$(cat <<'EOF'

<!-- AUTO_TOKEN70_BEGIN -->
# AUTO TOKEN-70 / QUALITY SAFE MODE

Always use this project by default in compressed high-quality mode.

Follow these rules for every answer:
- Reduce token usage by ~70% without reducing correctness.
- No preambles, no filler, no repetition of the user request.
- Use this format:
  [Логика/стратегия] — 1–2 предложения.
  [Финальный результат] — minimal complete result.
  [Инструкция] — 1 строка.
- Prefer diff-only edits.
- Output full files only when necessary.
- Read only relevant files.
- Do not scan the whole repository unless needed.
- Do not refactor unrelated code.
- Do not add dependencies without need.
- For debugging: cause → proof → fix → check command.
- For review: issue → risk → fix.
- For plans: max 7 steps.
- For scripts: one copy-pasteable safe script.
- Never modify server configs, VPN configs, keys, secrets, or production settings without the exact phrase: "Подтверждаю изменение конфига".
- Preserve quality over extreme compression.
- If more tokens are required for correctness, use them.

Detailed policy file:
.ai-token70/AUTO_TOKEN70_POLICY.md
<!-- AUTO_TOKEN70_END -->
EOF
)"

if [[ -f CLAUDE.md ]]; then
  cp CLAUDE.md ".ai-token70/backups/CLAUDE.md.$TS.bak"

  printf "%s\n" "$AUTO_BLOCK" > .ai-token70/.block.tmp

  python3 - <<'PY'
from pathlib import Path
p = Path("CLAUDE.md")
text = p.read_text(encoding="utf-8", errors="ignore")
start = "<!-- AUTO_TOKEN70_BEGIN -->"
end = "<!-- AUTO_TOKEN70_END -->"

block = Path(".ai-token70/.block.tmp").read_text(encoding="utf-8")

if start in text and end in text:
    before = text.split(start)[0].rstrip()
    after = text.split(end, 1)[1].lstrip()
    new = before + "\n\n" + block.strip() + "\n\n" + after
else:
    new = text.rstrip() + "\n\n" + block.strip() + "\n"

p.write_text(new, encoding="utf-8")
PY
else
  cat > CLAUDE.md <<EOF
# Project Instructions

$AUTO_BLOCK
EOF
fi

printf "%s\n" "$AUTO_BLOCK" > .ai-token70/.block.tmp
python3 - <<'PY'
from pathlib import Path
p = Path("CLAUDE.md")
block = Path(".ai-token70/.block.tmp").read_text(encoding="utf-8")
text = p.read_text(encoding="utf-8", errors="ignore")
start = "<!-- AUTO_TOKEN70_BEGIN -->"
end = "<!-- AUTO_TOKEN70_END -->"

if start in text and end in text:
    before = text.split(start)[0].rstrip()
    after = text.split(end, 1)[1].lstrip()
    new = before + "\n\n" + block.strip() + "\n\n" + after
else:
    new = text.rstrip() + "\n\n" + block.strip() + "\n"

p.write_text(new, encoding="utf-8")
PY
rm -f .ai-token70/.block.tmp

cat > .claude/commands/compact.md <<'EOF'
Use AUTO TOKEN-70 mode for this task.

Return only:
[Логика/стратегия] — 1–2 предложения.
[Финальный результат] — minimal complete result.
[Инструкция] — 1 строка.

Task:
$ARGUMENTS
EOF

cat > .ai-token70/check.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

echo "=== AUTO TOKEN-70 CHECK ==="

if [[ -f CLAUDE.md ]] && grep -q "AUTO_TOKEN70_BEGIN" CLAUDE.md; then
  echo "OK: CLAUDE.md patched"
else
  echo "FAIL: CLAUDE.md not patched"
  exit 1
fi

if [[ -f .ai-token70/AUTO_TOKEN70_POLICY.md ]]; then
  echo "OK: policy file exists"
else
  echo "FAIL: policy file missing"
  exit 1
fi

if [[ -f .claude/commands/compact.md ]]; then
  echo "OK: compact command exists"
else
  echo "WARN: compact command missing"
fi

echo "DONE"
EOF

chmod +x .ai-token70/check.sh

echo
echo "AUTO TOKEN-70 installed in: $ROOT"
