# aima-autohealer (prototype)

Probe → Detector → (future: Mutate → Apply) loop for VLESS+REALITY subscription
services like XSERVIS. Designed to slot in next to the existing
`/opt/xservis/backend/app/ai_telemetry` module on the production server.

This package is a **standalone prototype** that runs without XS11 access:
it ships realistic synthetic data so the detector can be inspected end to end.

## What's in this prototype

| Module | Purpose |
|---|---|
| `aima.types` | Pydantic models: `ProbeProfile`, `ProbeReport`, `Incident`, `BlockType`, `IncidentSeverity` |
| `aima.probe` | Async probes: TCP, TLS-with-SNI, HTTPS, DNS, UDP/QUIC. Classifies failures into `BlockType` |
| `aima.detector` | Rule + statistical engine. Groups by (profile, vantage), classifies incidents, suggests recipes |
| `aima.store` | SQLite persistence for profiles, reports, incidents |
| `aima.scheduler` | apscheduler `fast_loop` (5m) and `slow_loop` (60m) |
| `aima.api` | FastAPI: `POST /api/probe/report`, `GET /api/incidents`, `POST /api/detect/run`, … |
| `aima.cli` | Typer CLI: `aima init`, `aima probe`, `aima detect`, `aima demo`, `aima serve` |
| `aima.demo` | Synthetic dataset reproducing 4 RKN-style incidents across 5 vantage points |

## Block types we currently classify

```
NONE TCP_TIMEOUT TCP_RST DNS_BLOCK SNI_BLOCK REALITY_DETECT
QUIC_DROP HTTP_TAMPER THROTTLE UNKNOWN
```

Each `Incident` carries an ordered list of `suggested_recipes` (e.g.
`rotate_sni_pool`, `fallback_cdn_ws`, `rotate_pubkey`, `force_tcp_only`,
`switch_to_hysteria2`, …). The recipes are strings only at this stage —
the future `mutation_engine` module will register handlers for them.

## Quickstart

```bash
cd aima-autohealer
uv sync --extra dev          # creates .venv and installs deps
uv run aima demo             # synthetic timeline → detected incidents table
uv run aima init             # seed default direct-TLS profiles into aima.db
uv run aima probe            # probe once and store reports
uv run aima detect           # show incidents from the last 30 min
uv run aima serve --port 8765   # FastAPI on :8765 with 24/7 scheduler
uv run pytest                # full test suite (no network needed)
```

## How `aima demo` works

It seeds 45 minutes of synthetic probe reports across 5 vantages
(MTS / Beeline / Megafon / Yota / DigitalOcean baseline) and 4 profiles
(VLESS+REALITY @ Cloudflare SNI, @ Apple SNI, Hysteria2 UDP, DNS). Hidden in
the timeline are 4 RKN-style outages:

1. SNI block on Cloudflare REALITY from MTS-mobile starting at minute 5.
2. UDP/QUIC drop on Beeline from minute 10.
3. REALITY late-reset on Megafon from minute 15.
4. Throttle on Yota from minute 20 (RTT explodes after handshake).

The detector should produce ≥4 incidents tagged with the expected `block_type`
and the right `vantage`. The DigitalOcean baseline must remain incident-free.

## How it integrates with XSERVIS / AiMa later

* On XS11 the `aima` package is added to `/opt/xservis/backend/app/`.
* The existing `ai_telemetry_job` (apscheduler 15m) already produces verdicts
  but doesn't act. We replace it with `HealerScheduler.fast_loop` (5m) and
  feed the same telemetry through `detect_incidents`.
* External vantage points run a tiny client that POSTs `ProbeReport`s to
  `/api/probe/report` on XS11. They identify themselves via the `vantage`
  field; the detector groups by it.
* Future `mutation_engine` translates `suggested_recipes` into 3X-UI API
  calls + `sub_renderer.py` patches, with `apply.py`-level snapshot/rollback
  similar to the existing `fix*.sh` flow.

## Why some things are intentionally minimal

* **No real VLESS/REALITY client.** The prototype reproduces the *network
  signals* DPI operates on (TCP RST timing, TLS handshake outcome, late
  channel reset) instead of speaking the full proxy protocol. Slotting in
  a sing-box subprocess later is straightforward — see `probe.run_one` for
  the dispatch point.
* **No LLM yet.** The detector is fully deterministic and explainable. The
  `llm_decision.py` layer (Claude API loop) is the next milestone, only
  consulted when the deterministic catalog can't reach a confident verdict.
* **No mutation engine yet.** Recipes are emitted as labels; the actual
  `apply.py` lands in the next PR once we have XS11 access.
