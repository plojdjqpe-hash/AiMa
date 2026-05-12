"""Tests for the 3X-UI HTTP client (mocked server)."""

from __future__ import annotations

import json

import httpx
import pytest

from aima.xui_client import XUIClient, XUICreds, XUIError


@pytest.fixture
def creds() -> XUICreds:
    return XUICreds(base_url="http://panel.local", username="root", password="hunter2")


def _ok(payload: object) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "msg": "", "obj": payload})


def _fail(msg: str = "nope") -> httpx.Response:
    return httpx.Response(200, json={"success": False, "msg": msg})


@pytest.mark.asyncio
async def test_login_then_list(creds: XUIClient, httpx_mock) -> None:  # noqa: ANN001
    httpx_mock.add_response(
        url="http://panel.local/login", method="POST", json={"success": True, "msg": ""}
    )
    httpx_mock.add_response(
        url="http://panel.local/panel/api/inbounds/list",
        method="POST",
        json={"success": True, "msg": "", "obj": [{"id": 1, "port": 443}]},
    )
    async with XUIClient(creds) as c:
        ibs = await c.list_inbounds()
    assert ibs == [{"id": 1, "port": 443}]


@pytest.mark.asyncio
async def test_list_re_logs_in_on_403(creds: XUICreds, httpx_mock) -> None:  # noqa: ANN001
    httpx_mock.add_response(
        url="http://panel.local/login", method="POST", json={"success": True}
    )
    httpx_mock.add_response(
        url="http://panel.local/panel/api/inbounds/list",
        method="POST",
        status_code=403,
    )
    httpx_mock.add_response(
        url="http://panel.local/login", method="POST", json={"success": True}
    )
    httpx_mock.add_response(
        url="http://panel.local/panel/api/inbounds/list",
        method="POST",
        json={"success": True, "obj": []},
    )
    async with XUIClient(creds) as c:
        assert await c.list_inbounds() == []


@pytest.mark.asyncio
async def test_login_failure_raises(creds: XUICreds, httpx_mock) -> None:  # noqa: ANN001
    httpx_mock.add_response(
        url="http://panel.local/login",
        method="POST",
        json={"success": False, "msg": "wrong password"},
    )
    async with XUIClient(creds) as c:
        with pytest.raises(XUIError, match="wrong password"):
            await c.login()


@pytest.mark.asyncio
async def test_get_inbound_finds_by_id(creds: XUICreds, httpx_mock) -> None:  # noqa: ANN001
    httpx_mock.add_response(
        url="http://panel.local/login", method="POST", json={"success": True}
    )
    httpx_mock.add_response(
        url="http://panel.local/panel/api/inbounds/list",
        method="POST",
        json={
            "success": True,
            "obj": [{"id": 1, "port": 443}, {"id": 5, "port": 8443}],
        },
    )
    async with XUIClient(creds) as c:
        ib = await c.get_inbound(5)
    assert ib["port"] == 8443


@pytest.mark.asyncio
async def test_update_inbound_posts_full_object(creds: XUICreds, httpx_mock) -> None:  # noqa: ANN001
    httpx_mock.add_response(
        url="http://panel.local/login", method="POST", json={"success": True}
    )
    httpx_mock.add_response(
        url="http://panel.local/panel/api/inbounds/update/3",
        method="POST",
        json={"success": True, "obj": {"updated": True}},
    )
    async with XUIClient(creds) as c:
        result = await c.update_inbound(3, {"id": 3, "port": 443})
    assert result == {"updated": True}
    last = httpx_mock.get_request(url="http://panel.local/panel/api/inbounds/update/3")
    assert json.loads(last.content) == {"id": 3, "port": 443}
