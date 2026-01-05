from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

TokenUpdateCallback = Callable[[dict[str, Any]], Awaitable[None]]


class HarviaAuthError(Exception):
    """401 Unauthorized -> refresh/reauth needed."""


class HarviaApiError(Exception):
    """API error (incl. 403 Forbidden)."""


@dataclass(frozen=True)
class HarviaDevice:
    id: str
    type: str | None = None
    attrs: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


def _parse_attrs(attr_list: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(attr_list, list):
        return out

    for item in attr_list:
        if not isinstance(item, dict):
            continue

        key = item.get("key")
        value = item.get("value")
        if not key:
            continue

        if isinstance(value, str):
            v = value.strip()
            lv = v.lower()
            if lv == "true":
                value = True
            elif lv == "false":
                value = False
            else:
                try:
                    value = int(v)
                except ValueError:
                    try:
                        value = float(v)
                    except ValueError:
                        value = v

        out[str(key)] = value

    return out


class HarviaFenixApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        endpoints_url: str,
        username: str,
        password: Optional[str] = None,
        *,
        id_token: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
        token_obtained_at: Optional[int] = None,
        endpoints: Optional[dict[str, Any]] = None,
        request_timeout: int = 20,
        expiry_leeway_s: int = 60,
        token_update_callback: TokenUpdateCallback | None = None,
    ) -> None:
        self._session = session
        self._endpoints_url = endpoints_url
        self._username = username
        self._password = password

        self._id_token = id_token
        self._access_token = access_token
        self._refresh_token = refresh_token

        self._expires_in = int(expires_in) if expires_in else None
        self._token_obtained_at = int(token_obtained_at) if token_obtained_at else None
        self._expiry_leeway_s = max(0, int(expiry_leeway_s))

        self._endpoints = endpoints or {}
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)

        self._auth_lock = asyncio.Lock()
        self._token_update_callback = token_update_callback

        self._debug_requests = False
        self._debug_max_chars = 2000

    # ---------------- Debug ----------------
    def set_request_debug(self, enabled: bool, *, max_chars: int = 2000) -> None:
        self._debug_requests = bool(enabled)
        self._debug_max_chars = max(200, int(max_chars))

    # ---------------- Endpoints ----------------
    async def fetch_endpoints(self) -> dict[str, Any]:
        data = await self._request_json("GET", self._endpoints_url, auth=False)

        if not isinstance(data, dict):
            raise HarviaApiError("Endpoints response is not a dict")

        self._endpoints = data if "endpoints" in data else {"endpoints": data}
        return self._endpoints

    def _endpoints_root(self) -> dict[str, Any]:
        root = self._endpoints.get("endpoints")
        if not isinstance(root, dict):
            raise HarviaApiError("Missing endpoints root")
        return root

    def _restapi(self) -> dict[str, Any]:
        rest = self._endpoints_root().get("RestApi")
        if not isinstance(rest, dict):
            raise HarviaApiError("Missing endpoints.RestApi")
        return rest

    def _rest_base(self, service: str) -> str:
        rest = self._restapi()

        if service in rest and isinstance(rest[service], dict):
            https = rest[service].get("https")
            if isinstance(https, str):
                return https.rstrip("/")

        for env_node in rest.values():
            if isinstance(env_node, dict) and service in env_node:
                https = env_node[service].get("https")
                if isinstance(https, str):
                    return https.rstrip("/")

        raise HarviaApiError(f"RestApi base for '{service}' not found")

    # ---------------- Token handling ----------------
    def _token_expired_or_soon(self) -> bool:
        if not self._id_token:
            return True
        if not self._expires_in or not self._token_obtained_at:
            return False
        return time.time() >= (self._token_obtained_at + self._expires_in - self._expiry_leeway_s)

    async def ensure_valid_token(self) -> None:
        if self._token_expired_or_soon():
            if self._refresh_token:
                await self.refresh()
            else:
                raise HarviaAuthError("Token expired")

    async def login(self, password: Optional[str] = None) -> dict[str, Any]:
        pw = password or self._password
        if not pw:
            raise HarviaAuthError("Missing password")

        if not self._endpoints:
            await self.fetch_endpoints()

        url = f"{self._rest_base('generics')}/auth/token"
        data = await self._request_json(
            "POST",
            url,
            auth=False,
            json={"username": self._username, "password": pw},
            sensitive_request=True,
        )

        if not isinstance(data, dict) or not data.get("idToken"):
            raise HarviaAuthError("Login failed")

        self._id_token = data["idToken"]
        self._refresh_token = data.get("refreshToken")
        self._expires_in = int(data.get("expiresIn") or 0)
        self._token_obtained_at = int(time.time())

        if self._token_update_callback:
            await self._token_update_callback(
                {
                    "idToken": self._id_token,
                    "refreshToken": self._refresh_token,
                    "expiresIn": self._expires_in,
                    "tokenObtainedAt": self._token_obtained_at,
                }
            )

        return data

    async def refresh(self) -> dict[str, Any]:
        if not self._refresh_token:
            raise HarviaAuthError("No refresh token")

        url = f"{self._rest_base('generics')}/auth/refresh"
        data = await self._request_json(
            "POST",
            url,
            auth=False,
            json={"refreshToken": self._refresh_token},
            sensitive_request=True,
        )

        if not isinstance(data, dict) or not data.get("idToken"):
            raise HarviaAuthError("Refresh failed")

        self._id_token = data["idToken"]
        self._expires_in = int(data.get("expiresIn") or 0)
        self._token_obtained_at = int(time.time())
        return data

    def _auth_header(self) -> str:
        if not self._id_token:
            raise HarviaAuthError("Missing idToken")
        return f"Bearer {self._id_token}"

    # ---------------- API ----------------
    async def get_devices(self) -> list[HarviaDevice]:
        url = f"{self._rest_base('device')}/devices"
        data = await self._request_json("GET", url, auth=True)

        devices = data.get("devices", []) if isinstance(data, dict) else []
        out: list[HarviaDevice] = []

        for item in devices:
            dev_id = item.get("name") or item.get("id")
            if not dev_id:
                continue
            out.append(
                HarviaDevice(
                    id=str(dev_id),
                    type=item.get("type"),
                    attrs=_parse_attrs(item.get("attr")),
                    raw=item,
                )
            )
        return out

    async def get_device_state(self, device_id: str) -> dict[str, Any]:
        url = f"{self._rest_base('device')}/devices/state"
        return await self._request_json(
            "GET",
            url,
            auth=True,
            params={"deviceId": device_id},
        )

    async def get_latest_data(self, device_id: str) -> dict[str, Any]:
        """
        ✅ ONLY query-based endpoint:
        GET /data/latest-data?deviceId=<id>
        """
        url = f"{self._rest_base('data')}/data/latest-data"
        return await self._request_json(
            "GET",
            url,
            auth=True,
            params={"deviceId": device_id},
        )

    # ---------------- HTTP ----------------
    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        auth: bool,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        sensitive_request: bool = False,
    ) -> Any:
        headers = {"Accept": "application/json"}

        if auth:
            await self.ensure_valid_token()
            headers["Authorization"] = self._auth_header()

        if self._debug_requests:
            _LOGGER.debug(
                "Harvia REST REQ %s %s params=%s body=%s",
                method,
                url,
                params,
                None if sensitive_request else json,
            )

        async with self._session.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json,
            timeout=self._timeout,
        ) as resp:
            body = await resp.json() if "json" in resp.headers.get("Content-Type", "") else await resp.text()

            if resp.status == 401:
                raise HarviaAuthError("Unauthorized (401)")
            if resp.status == 403:
                raise HarviaApiError(f"Forbidden (403) for {url}")
            if resp.status >= 400:
                raise HarviaApiError(f"HTTP {resp.status}: {body}")

            return body

