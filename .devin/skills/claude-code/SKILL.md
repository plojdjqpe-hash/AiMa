---
name: claude-code
description: "Claude Code — AI-инструмент программирования от Anthropic. Установка, навыки, CLAUDE.md."
---

# Claude Code

AI-инструмент программирования: редактирование кода, команды, интеграция с IDE. Docs: https://code.claude.com/docs/llms.txt

## Установка

```bash
# macOS/Linux/WSL
curl -fsSL https://claude.ai/install.sh | bash
# Homebrew
brew install --cask claude-code
# Windows
irm https://claude.ai/install.ps1 | iex
```

## Команды

`/help` — список команд | `/resume` — продолжить сессию | `/compact` — сжать контекст | `/skill-name` — вызвать навык

## Навыки (Skills)

SKILL.md с YAML frontmatter → Claude добавляет в инструменты.

| Уровень | Путь |
|---------|------|
| Персональный | `~/.claude/skills/<name>/SKILL.md` |
| Проектный | `.claude/skills/<name>/SKILL.md` |

Frontmatter: `name`, `description`, `context` (fork/inline), `allowed-tools`

Динамическая инъекция: `` !`git diff HEAD` `` подставит вывод команды.

## CLAUDE.md

Файлы инструкций, загружаемые автоматически: `~/.claude/CLAUDE.md` (глобальный), `./CLAUDE.md` (проектный).

## Практики

1. Сначала пойми кодовую базу
2. Стандарты в CLAUDE.md
3. Навыки для повторяющихся задач
4. `/summarize-changes` перед коммитом
