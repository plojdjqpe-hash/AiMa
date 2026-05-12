---
name: ruflo
description: "Multi-agent оркестрация: swarm intelligence, SPARC methodology, RAG, security audit."
---

# Ruflo — Multi-Agent Orchestration

Координация 100+ AI-агентов через swarms, автономные workflows, self-learning memory.

## Плагины

**Core**: server + health checks | **Swarm**: координация агентов | **Autopilot**: автономный цикл | **Workflows**: многошаговые шаблоны | **Federation**: агенты на разных машинах

**Memory**: AgentDB (векторная БД) | RAG Memory (гибридный поиск) | Knowledge Graph (связи сущностей)

**Intelligence**: self-learning из успехов | Goals (декомпозиция целей → планы)

**Code Quality**: TestGen (генерация тестов) | Browser (Playwright E2E) | Jujutsu (анализ diff, оценка рисков) | Docs (автогенерация)

**Security**: Security Audit (CVE scan) | AI Defence (prompt injection, PII)

**Architecture**: ADR (архитектурные решения) | DDD (домены, агрегаты) | SPARC (5-фазная методология)

## SPARC Methodology

1. **Specification** — требования и критерии приёмки
2. **Pseudocode** — алгоритм перед кодом
3. **Architecture** — дизайн компонентов
4. **Refinement** — итеративное улучшение + тесты
5. **Completion** — верификация + документация

Каждая фаза имеет quality gate.

## Swarm Patterns

- **Divide & Conquer** — разбей → назначь агентам
- **Pipeline** — последовательная обработка
- **Consensus** — несколько агентов, сравнение результатов
- **Specialist Routing** — задача → агент с нужной специализацией
