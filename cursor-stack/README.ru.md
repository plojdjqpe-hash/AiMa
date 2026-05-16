# Cursor Stack — оптимизация токенов + персистентная память

Полный набор для Cursor IDE: 9 скиллов как Cursor Rules + Qdrant векторная память через MCP.

## Что внутри

```
cursor-stack/
├── install.ps1              # Установщик для Windows (PowerShell)
├── docker-compose.yml       # Qdrant контейнер
├── mcp.json.template        # Шаблон MCP конфига для Cursor
├── rules/                   # 9 скиллов как Cursor Rules (.mdc)
│   ├── superpowers.mdc
│   ├── code-review.mdc
│   ├── security-guidance.mdc
│   ├── frontend-design.mdc
│   ├── agency-agents.mdc
│   ├── gstack.mdc
│   ├── claude-mem.mdc
│   ├── claude-code.mdc
│   └── ruflo.mdc
├── BENCHMARK.md             # Замеры токенов до/после
└── README.ru.md             # Этот файл
```

## Быстрый старт (Windows)

### 1. Запусти Docker Desktop

Дождись пока иконка кита в трее станет стабильной (не анимирована).

Проверка:
```powershell
docker ps
```
Должна вернуть пустую таблицу с заголовками без ошибок.

### 2. Запусти установщик

```powershell
cd C:\путь\к\aima
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\cursor-stack\install.ps1
```

Скрипт:
- Поднимет Qdrant в Docker (порт 6333)
- Скопирует Cursor Rules в `%USERPROFILE%\.cursor\rules\`
- Создаст `%USERPROFILE%\.cursor\mcp.json` (или дополнит существующий)
- Запросит у тебя OpenAI API ключ для embeddings

### 3. Перезапусти Cursor

Полностью закрой Cursor (через трей) и открой снова. MCP подключится автоматически.

### 4. Проверь

В Cursor чате напиши:
```
@superpowers расскажи методологию TDD
```

Cursor должен подгрузить правило `superpowers.mdc`.

## Как это экономит токены

| Механизм | Эффект |
|----------|--------|
| Rules с `alwaysApply: false` | Загружаются только когда вызваны через `@` или релевантны — НЕ висят в контексте постоянно |
| Сжатые скиллы (этот PR) | 16k символов вместо 53k = **-69%** по содержимому |
| Qdrant память | Прошлые решения и контекст сохраняются — не нужно пересказывать каждую сессию |
| Точечные `globs` | Например `frontend-design.mdc` подключается только для `*.tsx`/`*.css` |

**Реальные цифры — в [BENCHMARK.md](./BENCHMARK.md).**

## Qdrant память — как работает

Cursor через MCP пишет важные наблюдения в Qdrant как векторы. При новой сессии релевантный контекст находится семантическим поиском и подгружается.

Сохраняются:
- Архитектурные решения и обоснования
- Решённые баги и корневые причины
- Конвенции проекта
- Настройки окружения

Storage: локальный Docker volume `qdrant_storage`. Не уходит в облако.

## OpenAI API ключ — зачем

Для embeddings (превращение текста в векторы). ~$0.02 за 1M токенов на `text-embedding-3-small`. Расходы минимальны (центы в месяц).

**Альтернатива без OpenAI** — раскомментируй `fastembed` секцию в `mcp.json.template`. Работает локально, бесплатно, медленнее.

## Безопасность

- ✅ Ключи хранятся только в `%USERPROFILE%\.cursor\mcp.json` (не в репо)
- ✅ Qdrant слушает только localhost (127.0.0.1)
- ✅ Не коммить `mcp.json` с заполненными ключами
- ❌ Никогда не показывай свой OpenAI ключ в чатах/issue/PR

## Удаление

```powershell
docker stop qdrant
docker rm qdrant
docker volume rm qdrant_storage
Remove-Item -Recurse "$env:USERPROFILE\.cursor\rules\superpowers.mdc"
# ... и остальные .mdc
```

## Troubleshooting

**`docker ps` возвращает 500** → Docker Desktop ещё стартует, подожди 1-2 минуты.

**Cursor не видит rules** → проверь что файлы в `%USERPROFILE%\.cursor\rules\*.mdc`, перезапусти Cursor через трей (не просто закрыть окно).

**MCP не подключается** → открой Cursor → Settings → MCP, проверь статус сервера. Логи в `%APPDATA%\Cursor\logs\`.
