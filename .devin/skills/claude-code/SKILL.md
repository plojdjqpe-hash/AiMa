---
name: claude-code
description: Руководство по использованию Claude Code — инструмента для автоматизированного программирования от Anthropic. Установка, настройка, создание навыков, лучшие практики.
---

# Claude Code

Claude Code — это инструмент для автоматизированного программирования, который считывает код, редактирует файлы, выполняет команды и интегрируется с инструментами разработки. Доступен в терминале, IDE, настольном приложении и браузере.

**Полный указатель документации:** https://code.claude.com/docs/llms.txt

## Установка

### macOS / Linux / WSL (рекомендуемый способ)

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

### Windows PowerShell

```powershell
irm https://claude.ai/install.ps1 | iex
```

### Windows CMD

```batch
curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
```

### Homebrew

```bash
brew install --cask claude-code
```

### WinGet

```powershell
winget install Anthropic.ClaudeCode
```

> На Windows рекомендуется установить [Git for Windows](https://gitforwindows.org/), чтобы Claude Code мог использовать Bash. Если Git for Windows не установлен, Claude Code будет использовать PowerShell.

Нативные установки автоматически обновляются в фоновом режиме. Homebrew и WinGet требуют ручного обновления (`brew upgrade claude-code` / `winget upgrade Anthropic.ClaudeCode`).

## Быстрый старт

### 1. Авторизация

```bash
claude
# При первом запуске будет предложено войти в систему
```

Поддерживаемые аккаунты:
- Claude Pro, Max, Team, Enterprise
- Claude Console (API с предоплаченными кредитами)
- Amazon Bedrock, Google Vertex AI, Microsoft Foundry

### 2. Первая сессия

```bash
cd /path/to/your/project
claude
```

### 3. Полезные команды

| Команда | Описание |
|---------|----------|
| `/help` | Список доступных команд |
| `/resume` | Продолжить предыдущий разговор |
| `/compact` | Сжать контекст разговора |
| `/login` | Сменить аккаунт |
| `/skill-name` | Вызвать навык по имени |

### 4. Примеры запросов

```text
what does this project do?
explain the folder structure
find and fix the bug in auth module
write tests for the User class
create a PR with my changes
```

## Навыки (Skills)

Навыки расширяют возможности Claude. Создайте файл `SKILL.md` с инструкциями, и Claude добавит его в свой набор инструментов.

### Когда создавать навык

- Вы повторно вставляете одни и те же инструкции
- Раздел CLAUDE.md вырос в процедуру, а не в факт
- Нужно стандартизировать рабочий процесс в команде

### Расположение навыков

| Уровень | Путь | Область действия |
|---------|------|-----------------|
| Корпоративный | Managed settings | Все пользователи организации |
| Персональный | `~/.claude/skills/<name>/SKILL.md` | Все ваши проекты |
| Проектный | `.claude/skills/<name>/SKILL.md` | Только текущий проект |
| Плагин | `<plugin>/skills/<name>/SKILL.md` | Где плагин включён |

### Структура навыка

```text
my-skill/
├── SKILL.md           # Главные инструкции (обязательно)
├── template.md        # Шаблон для заполнения
├── examples/
│   └── sample.md      # Пример вывода
└── scripts/
    └── validate.sh    # Скрипт для выполнения
```

### Пример: навык для анализа изменений

```yaml
---
description: Суммирует незафиксированные изменения и отмечает риски.
---

## Текущие изменения

!`git diff HEAD`

## Инструкции

Суммируйте изменения выше в 2-3 пунктах, затем перечислите
риски: отсутствие обработки ошибок, захардкоженные значения,
тесты, которые нужно обновить.
```

### Frontmatter (YAML-заголовок)

| Поле | Описание |
|------|----------|
| `name` | Имя навыка (строчные буквы, цифры, дефисы, до 64 символов) |
| `description` | Что делает навык и когда его использовать |
| `context` | `fork` — выполнять в субагенте, `inline` — в текущем контексте |
| `disable-model-invocation` | `true` — только ручной вызов через `/skill-name` |
| `allowed-tools` | Список разрешённых инструментов |

### Типы контента навыков

**Справочный контент** — знания, которые Claude применяет к текущей работе:

```yaml
---
name: api-conventions
description: Паттерны проектирования API для этой кодовой базы
---

При написании API-эндпоинтов:
- Используйте RESTful именование
- Возвращайте единообразный формат ошибок
- Включайте валидацию запросов
```

**Задачный контент** — пошаговые инструкции для конкретного действия:

```yaml
---
name: deploy
description: Деплой приложения в продакшен
context: fork
disable-model-invocation: true
---

Деплой приложения:
1. Запустите тесты
2. Соберите приложение
3. Отправьте на целевой сервер
```

### Динамическая инъекция контекста

Используйте `!` с обратными кавычками для подстановки вывода команд:

```markdown
!`git diff HEAD`         # Подставит текущий diff
!`cat config.json`       # Подставит содержимое файла
!`npm test 2>&1`         # Подставит результат тестов
```

## Файлы CLAUDE.md

CLAUDE.md — файлы инструкций для Claude, загружаемые автоматически:

| Расположение | Описание |
|-------------|----------|
| `~/.claude/CLAUDE.md` | Глобальные инструкции |
| `./CLAUDE.md` | Инструкции проекта |
| `./.claude/CLAUDE.md` | Альтернативное расположение |

Содержимое CLAUDE.md загружается всегда, в отличие от навыков, которые загружаются только при необходимости.

## Интерфейсы Claude Code

| Цель | Интерфейс |
|------|----------|
| Полнофункциональная работа в терминале | Terminal CLI |
| Интеграция с IDE | VS Code, JetBrains |
| Работа с десктопа | Desktop App |
| Работа из браузера | Web |
| Продолжить сессию с другого устройства | Remote |
| Автоматизация CI/CD | GitHub Actions, GitLab CI/CD |
| Интеграция с мессенджерами | Slack, Telegram, Discord (Channels) |
| Отладка веб-приложений | Chrome |
| Создание собственных агентов | Agent SDK |
| Планирование задач | Scheduled Tasks |

## Лучшие практики

1. **Начните с понимания кодовой базы** — попросите Claude проанализировать проект перед внесением изменений
2. **Используйте CLAUDE.md** — добавьте стандарты проекта, чтобы Claude следовал им
3. **Создавайте навыки** для повторяющихся задач
4. **Проверяйте изменения** — используйте `/summarize-changes` перед коммитом
5. **Настройте MCP-серверы** для подключения к внешним инструментам
6. **Используйте хуки** для перехвата и кастомизации поведения агента

## Полезные ссылки

- [Документация](https://code.claude.com/docs)
- [Указатель документов](https://code.claude.com/docs/llms.txt)
- [Навыки](https://code.claude.com/docs/en/skills.md)
- [Быстрый старт](https://code.claude.com/docs/en/quickstart.md)
- [Лучшие практики](https://code.claude.com/docs/en/best-practices.md)
- [Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview.md)
- [CLI справка](https://code.claude.com/docs/en/cli-reference.md)
