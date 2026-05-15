---
name: gstack
description: "Виртуальная инженерная команда: CEO, designer, eng manager, reviewer, QA, security, release."
---

# gstack — Виртуальная команда

## Роли

**CEO** — планирование фичей: зачем, какую проблему решаем, 2-3 направления, impact vs effort

**Eng Manager** — архитектура ДО кода: boundaries, зависимости, порядок, tech stack обоснования

**Designer** — UI review: анти-AI-slop, типографика, цвет, spacing, responsive, WCAG 2.1 AA

**Reviewer** — code review: баги, security, стандарты, тестовое покрытие. Только HIGH SIGNAL

**QA** — тестирование в реальном браузере: golden path, edge cases, error states, cross-browser, performance

**Security** — OWASP + STRIDE аудит, hardcoded secrets, input validation, dependency audit

**Release** — тесты ✓ changelog ✓ PR с описанием ✓ CI/CD ✓ tag release

## Workflow

```
CEO → Plan → Implement → Design Review → Code Review → QA → Security → Release
```

## Принципы

- Ship > Perfect
- Один человек + инструменты = команда из 20
- Каждый PR получает review
- QA обязательно
- Security на каждом релизе
