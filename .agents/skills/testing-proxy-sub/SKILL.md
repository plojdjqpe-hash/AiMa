---
name: testing-proxy-sub
description: Test the proxy-sub subscription service end-to-end. Use when verifying proxy filtering, endpoint behavior, or subscription format changes.
---

# Testing proxy-sub Service

## Setup

```bash
cd proxy-sub
pip install -e .
uvicorn main:app --host 0.0.0.0 --port 8000
```

No auth required. All endpoints are public.

## Key Endpoints

| Endpoint | Purpose | Expected behavior |
|----------|---------|-------------------|
| /stats | Aggregated config stats | total_configs > 100, sources_count == 7 |
| /sub/lte | LTE-optimized configs | All REALITY, LTE-safe ports, 📡LTE- labels |
| /sub/wifi | WiFi-optimized configs | All security=tls, 🌐WiFi- labels, zero REALITY |
| /sub/3g | 3G-optimized configs | LTE-safe ports, 📶3G- labels |
| /sub/best | Top 20 by score | <= 20 configs, labels match best_for field |
| /sub?network=X&max=N&ports=P | Flexible query | Respects all params, strict filtering |

## Critical Test: WiFi Filtering

The WiFi endpoint historically had a bug where it returned REALITY/LTE configs instead of WS/TLS configs. Always verify:
- `/sub/wifi` returns ZERO `security=reality` configs
- ALL configs have `security=tls`
- Labels are 🌐WiFi- not 📡LTE-

## Quick Verification Script

```bash
# WiFi bug check
reality_in_wifi=$(curl -s http://localhost:8000/sub/wifi | grep 'security=reality' | wc -l)
echo "REALITY in WiFi: $reality_in_wifi (should be 0)"

# Port filter check
bad_ports=$(curl -s 'http://localhost:8000/sub?ports=2096&max=5' | grep '^vless://' | grep -v ':2096' | wc -l)
echo "Wrong ports: $bad_ports (should be 0)"

# Max limit check
count=$(curl -s 'http://localhost:8000/sub?network=wifi&max=5' | grep -c '^vless://')
echo "Config count: $count (should be 5)"
```

## Common Issues

- **WiFi returns LTE configs**: Check `build_subscription()` WiFi filter — must skip non-TLS/non-WS configs
- **Labels don't match network**: Labeling should use requested `network` param, not `best_for` field
- **Cache not working**: Check `_cache["last_update"] > 0` guard (empty list `[]` is falsy)
- **SS dedup too aggressive**: SS dedup key must include `method:password`, not just `host:port`
- **Shortcut endpoints ignore query params**: `/sub/lte`, `/sub/wifi` etc. hardcode max_configs — use `/sub?network=wifi&max=N` for custom limits

## Devin Secrets Needed

None — service uses public GitHub raw URLs as config sources.
