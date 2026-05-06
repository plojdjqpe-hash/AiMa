"""Async 3X-UI REST client.

Speaks to the 3X-UI panel that XSERVIS runs alongside its FastAPI backend.
The URL pattern observed on XS11 is `http://host.docker.internal:38669/{path}/panel/api/...`.
Credentials are read at runtime on the server from environment variables —
never persisted in this repo.

Implements only the endpoints the auto-healer needs:
    POST   /{base}/login                     — login, sets `3x-ui` cookie
    POST   /{base}/panel/api/inbounds/list   — list all inbounds
    POST   /{base}/panel/api/inbounds/update/{id}   — replace one inbound
    POST   /{base}/panel/api/inbounds/addClient
    POST   /{base}/panel/api/inbounds/{id}/delClient/{email}

The client is intentionally tolerant: 3X-UI versions differ slightly in
response envelopes (`{success, msg, obj}` vs `{ok, data}`) so we normalize.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class XUICreds:
    """Credentials needed to talk to the 3X-UI REST API.

    On XS11 these come from the production `/opt/xservis/.env`:
        XUI_BASE_URL=http://host.docker.internal:38669/<webBasePath>
        XUI_USERNAME=...
        XUI_PASSWORD=...
    """

    base_url: str
    username: str
    password: str
    timeout_s: float = 10.0
    verify_tls: bool = True

    @classmethod
    def from_env(cls, prefix: str = "XUI_") -> XUICreds:
        try:
            base = os.environ[f"{prefix}BASE_URL"].rstrip("/")
            user = os.environ[f"{prefix}USERNAME"]
            pwd = os.environ[f"{prefix}PASSWORD"]
        except KeyError as exc:
            raise RuntimeError(
                f"missing env var {exc!s}; export {prefix}BASE_URL, "
                f"{prefix}USERNAME, {prefix}PASSWORD on the host"
            ) from exc
        return cls(
            base_url=base,
            username=user,
            password=pwd,
            timeout_s=float(os.environ.get(f"{prefix}TIMEOUT", "10")),
            verify_tls=os.environ.get(f"{prefix}VERIFY_TLS", "1") not in ("0", "false", "False"),
        )


class XUIError(RuntimeError):
    """Raised when the panel returns success=false, an HTTP error, or invalid JSON."""


class XUIClient:
    """Async 3X-UI REST client. Use as `async with XUIClient(creds) as c:`."""

    def __init__(self, creds: XUICreds) -> None:
        self.creds = creds
        self._client: httpx.AsyncClient | None = None
        self._logged_in = False

    async def __aenter__(self) -> XUIClient:
        self._client = httpx.AsyncClient(
            base_url=self.creds.base_url,
            timeout=self.creds.timeout_s,
            verify=self.creds.verify_tls,
            follow_redirects=False,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("XUIClient must be used as an async context manager")
        return self._client

    @staticmethod
    def _envelope(payload: object) -> object:
        """Pull `obj`/`data` out of common 3X-UI response envelopes."""

        if not isinstance(payload, dict):
            raise XUIError(f"unexpected non-object response: {payload!r}")
        if payload.get("success") is False:
            raise XUIError(payload.get("msg") or "panel returned success=false")
        if "obj" in payload:
            return payload["obj"]
        if "data" in payload:
            return payload["data"]
        return payload

    async def login(self) -> None:
        """POST /login with form-encoded credentials. Raises XUIError on failure."""

        resp = await self.client.post(
            "/login",
            data={"username": self.creds.username, "password": self.creds.password},
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise XUIError(f"login: panel returned non-JSON ({len(resp.text)} bytes)") from exc
        if isinstance(payload, dict) and payload.get("success") is False:
            raise XUIError(f"login failed: {payload.get('msg') or payload}")
        self._logged_in = True
        logger.info("xui: logged in to %s", self.creds.base_url)

    async def _post(self, path: str, *, json_body: object | None = None) -> object:
        if not self._logged_in:
            await self.login()
        resp = await self.client.post(path, json=json_body)
        if resp.status_code in (302, 401, 403):
            # cookie expired — re-login and retry once
            self._logged_in = False
            await self.login()
            resp = await self.client.post(path, json=json_body)
        resp.raise_for_status()
        try:
            return self._envelope(resp.json())
        except json.JSONDecodeError as exc:
            raise XUIError(f"{path}: invalid JSON in response") from exc

    # ─── Inbounds ───────────────────────────────────────────────────────────

    async def list_inbounds(self) -> list[dict]:
        result = await self._post("/panel/api/inbounds/list")
        if not isinstance(result, list):
            raise XUIError(f"list_inbounds: expected list, got {type(result).__name__}")
        return result

    async def get_inbound(self, inbound_id: int) -> dict:
        for ib in await self.list_inbounds():
            if int(ib.get("id", -1)) == inbound_id:
                return ib
        raise XUIError(f"inbound {inbound_id} not found")

    async def update_inbound(self, inbound_id: int, inbound: dict) -> dict:
        """Replace one inbound. The API expects the full inbound object."""

        result = await self._post(
            f"/panel/api/inbounds/update/{inbound_id}", json_body=inbound
        )
        return result if isinstance(result, dict) else {}

    async def add_inbound(self, inbound: dict) -> dict:
        result = await self._post("/panel/api/inbounds/add", json_body=inbound)
        return result if isinstance(result, dict) else {}

    async def del_inbound(self, inbound_id: int) -> None:
        await self._post(f"/panel/api/inbounds/del/{inbound_id}")

    # ─── Clients on inbounds ────────────────────────────────────────────────

    async def add_client(self, inbound_id: int, client: dict) -> dict:
        body = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        result = await self._post("/panel/api/inbounds/addClient", json_body=body)
        return result if isinstance(result, dict) else {}

    async def del_client(self, inbound_id: int, email: str) -> None:
        await self._post(f"/panel/api/inbounds/{inbound_id}/delClient/{email}")
