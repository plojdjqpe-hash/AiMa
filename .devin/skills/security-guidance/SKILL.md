---
name: security-guidance
description: "Руководство по безопасности кода. Проверка на уязвимости, security patterns, OWASP, STRIDE. Используй при редактировании кода, связанного с безопасностью."
---

# Security Guidance — Безопасность кода

Источник: [anthropics/claude-code/plugins/security-guidance](https://github.com/anthropics/claude-code/tree/main/plugins/security-guidance) (Anthropic)

Руководство по обнаружению и предотвращению уязвимостей при разработке. Автоматическая проверка security patterns в редактируемом коде.

---

## Основные правила

1. **Никогда** не expose или log секреты/ключи
2. **Никогда** не коммить credentials (.env, credentials.json, etc.)
3. **Всегда** валидируй и санитизируй пользовательский ввод
4. **Всегда** используй параметризованные запросы (не конкатенацию строк)
5. **Всегда** проверяй авторизацию на каждом эндпоинте

---

## Security Patterns по категориям

### GitHub Actions Workflows
При редактировании `.github/workflows/*.yml`:
- **Command Injection**: Никогда не используй недоверенный input напрямую в `run:` командах
- Используй `env:` variables вместо `${{ github.event.issue.title }}`
- Ревьюй: https://github.blog/security/vulnerability-research/how-to-catch-github-actions-workflow-injections-before-attackers-do/

### API и Web-приложения
- **SQL Injection**: Параметризованные запросы, ORM
- **XSS**: Экранирование вывода, Content Security Policy
- **CSRF**: Токены для мутирующих операций
- **SSRF**: Валидация URL, whitelist доменов
- **Path Traversal**: Нормализация путей, запрет `../`

### Аутентификация и авторизация
- Используй проверенные библиотеки (bcrypt, argon2 для хэширования)
- JWT: проверяй алгоритм, срок действия, issuer
- Session: secure, httponly, samesite cookies
- Rate limiting на login endpoints

### Криптография
- Не пиши свою криптографию
- Используй AES-256-GCM для шифрования
- RSA минимум 2048 бит, предпочтительно Ed25519
- Безопасный random: `crypto.randomBytes()`, `secrets.token_hex()`

### Зависимости
- Проверяй зависимости на известные уязвимости (`npm audit`, `pip audit`)
- Фиксируй версии зависимостей
- Минимизируй количество зависимостей

---

## OWASP Top 10 — Чеклист

1. **Broken Access Control** — проверяй авторизацию на каждом уровне
2. **Cryptographic Failures** — шифруй sensitive data at rest и in transit
3. **Injection** — параметризация всех запросов
4. **Insecure Design** — threat modeling перед реализацией
5. **Security Misconfiguration** — минимальные привилегии, отключи debug в prod
6. **Vulnerable Components** — обновляй зависимости, аудит
7. **Authentication Failures** — MFA, rate limiting, secure session management
8. **Data Integrity Failures** — подписывай и верифицируй updates
9. **Logging Failures** — логируй security events, не логируй PII
10. **SSRF** — валидируй все URL, whitelist

---

## STRIDE Threat Model

При проектировании новых фич, проверь каждую категорию:

| Угроза | Вопрос |
|--------|--------|
| **Spoofing** | Можно ли подделать identity? |
| **Tampering** | Можно ли изменить данные в transit/at rest? |
| **Repudiation** | Есть ли audit trail? |
| **Information Disclosure** | Утечка sensitive data? |
| **Denial of Service** | Можно ли перегрузить систему? |
| **Elevation of Privilege** | Можно ли получить чужие права? |

---

## При каждом ревью кода проверяй

- [ ] Нет hardcoded secrets
- [ ] Input validation на всех entry points
- [ ] Правильная обработка ошибок (без раскрытия internals)
- [ ] Логирование security-значимых событий
- [ ] Минимальные привилегии для каждого компонента
- [ ] HTTPS/TLS для всех внешних коммуникаций
