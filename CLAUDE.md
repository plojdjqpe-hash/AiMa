# Project Instructions

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

