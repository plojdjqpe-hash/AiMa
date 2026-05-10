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
