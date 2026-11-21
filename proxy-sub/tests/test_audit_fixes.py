"""Regression tests for the 2026-11 audit fixes (endpoint validation, refresh hardening, bot)."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main
import nodes


@pytest.mark.parametrize(
    "line",
    [
        "vless://u@:443?security=tls",            # empty host
        "vless://u@example.com:0",                # port 0
        "vless://u@example.com:99999",            # port out of range
        "trojan://p@example.com:70000",
        "vless://u@127.0.0.1:6379",               # loopback → SSRF on our own Redis
        "vless://u@10.0.0.5:443",                 # private network
        "vless://u@192.168.1.1:443",
        "vless://u@169.254.169.254:80",           # cloud metadata
        "vless://u@[::1]:443",
        "vless://u@[fe80::1]:443",
        "vless://u@localhost:443",
        "vless://u@router.local:443",
        "ss://YWVzLTEyOC1nY206cA@example.com:999999",
    ],
)
def test_parse_line_rejects_unusable_or_internal_endpoints(line):
    assert main.parse_line(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "vless://u@example.com:443?security=reality&flow=xtls-rprx-vision",
        "vless://u@1.1.1.1:8443",
        "vless://u@[2606:4700::1111]:443",
        "trojan://p@example.com:443?sni=example.com",
    ],
)
def test_parse_line_keeps_public_endpoints(line):
    assert main.parse_line(line) is not None


def test_valid_endpoint_edge_cases():
    assert nodes.valid_endpoint("example.com", 443)
    assert not nodes.valid_endpoint("example.com", "443")
    assert not nodes.valid_endpoint("example.com", True)
    assert not nodes.valid_endpoint("::ffff:127.0.0.1", 443)
    assert not nodes.valid_endpoint("224.0.0.1", 443)


def test_public_refresh_is_rate_limited(monkeypatch):
    from fastapi.testclient import TestClient

    calls = []

    async def fake_fetch(force=False):
        calls.append(force)
        return []

    monkeypatch.setattr(main, "fetch_configs", fake_fetch)
    monkeypatch.delenv("REFRESH_TOKEN", raising=False)
    monkeypatch.setitem(main._cache, "last_update", main.time.time())
    c = TestClient(main.app)
    r = c.post("/refresh")
    assert r.status_code == 200 and r.json().get("cached") is True
    assert calls == []  # no re-download within the cooldown

    monkeypatch.setitem(main._cache, "last_update", 0)
    assert c.post("/refresh").status_code == 200
    assert calls == [True]


def test_token_refresh_bypasses_cooldown(monkeypatch):
    from fastapi.testclient import TestClient

    calls = []

    async def fake_fetch(force=False):
        calls.append(force)
        return []

    monkeypatch.setattr(main, "fetch_configs", fake_fetch)
    monkeypatch.setenv("REFRESH_TOKEN", "secret")
    monkeypatch.setitem(main._cache, "last_update", main.time.time())
    c = TestClient(main.app)
    assert c.post("/refresh", headers={"X-Refresh-Token": "wrong"}).status_code == 403
    assert c.post("/refresh", headers={"X-Refresh-Token": "secret"}).status_code == 200
    assert calls == [True]


def test_bot_hides_non_https_webapp_button(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    import bot

    assert not bot.webapp_url_ok("http://1.2.3.4:8000/app")
    assert not bot.webapp_url_ok("https://127.0.0.1/app")
    assert bot.webapp_url_ok("https://sub.example.com/app")

    monkeypatch.setattr(bot, "WEBAPP_URL", "http://1.2.3.4:8000/app")
    kb = bot.main_keyboard()
    assert not any(b.web_app for row in kb.inline_keyboard for b in row)
    monkeypatch.setattr(bot, "WEBAPP_URL", "https://sub.example.com/app")
    kb = bot.main_keyboard()
    assert any(b.web_app for row in kb.inline_keyboard for b in row)


def test_bot_callback_counts_all_protocols(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    import bot

    requested = []

    async def fake_get(path, with_headers=False):
        requested.append(path)
        return "//profile-title: x\n\nvless://a@h:443#1\ntrojan://p@h:443#2\nhy2://p@h:443#3\n"

    edits = []

    class Msg:
        async def edit_text(self, text, reply_markup=None):
            edits.append(text)

    class Cb:
        message = Msg()

    monkeypatch.setattr(bot, "api_get", fake_get)
    asyncio.run(bot.send_sub_callback(Cb(), "lte", "LTE"))
    assert requested == ["/sub/lte?format=uri"]
    assert "(3 конфигов)" in edits[-1]


def test_geo_resolve_times_out(monkeypatch):
    import geo

    async def slow_getaddrinfo(*_a, **_k):
        await asyncio.sleep(5)

    async def run():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", slow_getaddrinfo)
        monkeypatch.setattr(geo, "DNS_TIMEOUT", 0.05)
        return await geo._resolve_ip("slow.example.com")

    assert asyncio.run(run()) is None
