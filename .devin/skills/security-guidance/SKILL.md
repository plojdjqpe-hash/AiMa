---
name: security-guidance
description: "Безопасность кода: OWASP Top 10, STRIDE, security patterns."
---

# Security Guidance

## Правила

- Не expose/log секреты. Не коммить .env/credentials
- Валидируй и санитизируй весь input
- Параметризованные запросы (не конкатенация строк)
- Проверяй авторизацию на каждом эндпоинте

## Security Patterns

**GitHub Actions**: env variables вместо `${{ github.event.* }}` в run

**Web**: SQL Injection (ORM/параметры), XSS (экранирование, CSP), CSRF (токены), SSRF (whitelist URL), Path Traversal (нормализация, запрет `../`)

**Auth**: bcrypt/argon2, JWT (проверяй алгоритм/expiry/issuer), secure/httponly/samesite cookies, rate limiting

**Crypto**: не своя криптография, AES-256-GCM, Ed25519, `crypto.randomBytes()`/`secrets.token_hex()`

**Deps**: `npm audit`/`pip audit`, фиксированные версии

## OWASP Top 10

1. Broken Access Control — авторизация на каждом уровне
2. Crypto Failures — шифрование at rest + in transit
3. Injection — параметризация
4. Insecure Design — threat modeling
5. Misconfiguration — минимальные привилегии, нет debug в prod
6. Vulnerable Components — audit + обновления
7. Auth Failures — MFA, rate limiting
8. Data Integrity — подпись и верификация updates
9. Logging Failures — логируй security events, не PII
10. SSRF — whitelist URL

## STRIDE

| Угроза | Проверь |
|--------|---------|
| Spoofing | подделка identity? |
| Tampering | изменение данных? |
| Repudiation | есть audit trail? |
| Info Disclosure | утечка sensitive data? |
| DoS | перегрузка системы? |
| Elevation | чужие права? |
