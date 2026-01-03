from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_ENDPOINTS_URL = "https://api.harvia.io/endpoints"


class HarviaAuthError(Exception):
    """Raised when API calls fail due to authentication (401/403)."""


@dataclass
class HarviaTokens:
    id_token: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None  # epoch seconds


@dataclass
class HarviaDevice:
    id: str
    type: str
    name: str
    attr: list[dict[str, Any]]
    state: dict[str, Any] | None = None


class HarviaSaunaAPI:
    def __init__(
        self,
        hass,
        username: str,
        password: str,
        endpoints_url: str = DEFAULT_ENDPOINTS_URL,
    ) -> None:
        self._hass = hass
        self._username = username
        self._password = password
        self._endpoints_url = endpoints_url

        self._session: aiohttp.ClientSession | None = None
        self._tokens = HarviaTokens()

        self._endpoints_loaded = False
        self._rest_generics_base: str | None = None
        self._rest_device_base: str | None = None

        self._auth_lock = asyncio.Lock()
        self._expiry_skew = 60  # refresh 60s before expiry

    # -----------------------------
    # Init / lifecycle
    # -----------------------------

    async def async_init(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()

        if not self._endpoints_loaded:
            await self._load_endpoints()

        if not self._rest_generics_base or not self._rest_device_base:
            raise RuntimeError(
                f"Harvia endpoints not initialized (generics={self._rest_generics_base}, device={self._rest_device_base})"
            )

        if not self._tokens.id_token:
            await self._authenticate()

        if not self._tokens.id_token:
            raise HarviaAuthError("Harvia auth failed: no idToken")

    async def close(self) -> None:
        if self._session:
            await self._session.close()
        self._session = None

    # -----------------------------
    # Endpoints
    # -----------------------------

    async def _load_endpoints(self) -> None:
        assert self._session is not None

        _LOGGER.debug("Harvia: loading endpoints from %s", self._endpoints_url)

        async with self._session.get(
            self._endpoints_url,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"Accept": "application/json"},
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Failed to load endpoints {resp.status}: {text}")
            data = json.loads(text) if text else {}

        try:
            rest_api = data["endpoints"]["RestApi"]
            rest_generic = rest_api["generics"]["https"]
            rest_device = rest_api["device"]["https"]
        except Exception as err:
            raise RuntimeError(f"Endpoints parsing failed: {data}") from err

        self._rest_generics_base = str(rest_generic).rstrip("/")
        self._rest_device_base = str(rest_device).rstrip("/")
        self._endpoints_loaded = True

        _LOGGER.info(
            "Harvia endpoints resolved: generics=%s device=%s",
            self._rest_generics_base,
            self._rest_device_base,
        )

    # -----------------------------
    # Auth (token + refresh)
    # -----------------------------

    async def _authenticate(self) -> None:
        assert self._session is not None
        assert self._rest_generics_base is not None

        url = f"{self._rest_generics_base}/auth/token"
        payload = {"username": self._username, "password": self._password}

        _LOGGER.debug("Harvia AUTH POST %s", url)

        async with self._session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"Accept": "application/json"},
        ) as resp:
            text = await resp.text()
            if resp.status in (401, 403):
                raise HarviaAuthError(f"Auth rejected ({resp.status}): {text}")
            if resp.status >= 400:
                raise RuntimeError(f"Auth failed {resp.status}: {text}")
            data = json.loads(text) if text else {}

        self._apply_token_payload(data, keep_refresh_if_missing=False)
        _LOGGER.info(
            "Harvia auth OK (idToken=%s refreshToken=%s)",
            bool(self._tokens.id_token),
            bool(self._tokens.refresh_token),
        )

    async def _refresh(self) -> bool:
        assert self._session is not None
        assert self._rest_generics_base is not None

        if not self._tokens.refresh_token:
            _LOGGER.debug("Harvia refresh skipped: no refresh_token")
            return False

        url = f"{self._rest_generics_base}/auth/refresh"
        payload = {"refreshToken": self._tokens.refresh_token, "email": self._username, "username": self._username}

        _LOGGER.debug("Harvia AUTH REFRESH POST %s", url)

        async with self._session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"Accept": "application/json"},
        ) as resp:
            text = await resp.text()
            if resp.status in (401, 403):
                _LOGGER.warning("Harvia refresh rejected (%s): %s", resp.status, text)
                return False
            if resp.status >= 400:
                _LOGGER.warning("Harvia refresh failed (%s): %s", resp.status, text)
                return False
            data = json.loads(text) if text else {}

        self._apply_token_payload(data, keep_refresh_if_missing=True)
        _LOGGER.info("Harvia token refresh OK (idToken=%s)", bool(self._tokens.id_token))
        return bool(self._tokens.id_token)

    def _apply_token_payload(self, data: dict[str, Any], *, keep_refresh_if_missing: bool) -> None:
        id_token = data.get("idToken") or data.get("id_token")
        access_token = data.get("accessToken") or data.get("access_token")
        refresh_token = data.get("refreshToken") or data.get("refresh_token")
        expires_in = data.get("expiresIn") or data.get("expires_in")

        if id_token:
            self._tokens.id_token = id_token
        if access_token:
            self._tokens.access_token = access_token

        if refresh_token:
            self._tokens.refresh_token = refresh_token
        elif not keep_refresh_if_missing:
            self._tokens.refresh_token = None

        if expires_in is not None:
            try:
                self._tokens.expires_at = time.time() + float(expires_in)
            except Exception:
                self._tokens.expires_at = None

    def _token_needs_refresh(self) -> bool:
        if not self._tokens.id_token:
            return True
        if not self._tokens.expires_at:
            return False
        return time.time() >= (self._tokens.expires_at - self._expiry_skew)

    async def _ensure_valid_token(self, *, force: bool = False) -> None:
        async with self._auth_lock:
            await self.async_init()

            if force or self._token_needs_refresh():
                ok = await self._refresh()
                if not ok:
                    await self._authenticate()

            if not self._tokens.id_token:
                raise HarviaAuthError("No valid token after refresh/auth")

    # -----------------------------
    # REST helper (refresh+retry)
    # -----------------------------

    async def rest_call(
        self,
        base: str | None,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        await self.async_init()
        assert self._session is not None

        if not base:
            raise RuntimeError(
                f"Harvia rest_call base URL is missing. "
                f"Endpoints loaded={self._endpoints_loaded} generics={self._rest_generics_base} device={self._rest_device_base}"
            )

        url = f"{base.rstrip('/')}/{path.lstrip('/')}"

        for attempt in range(2):
            await self._ensure_valid_token(force=(attempt == 1))

            headers = {"Authorization": f"Bearer {self._tokens.id_token}", "Accept": "application/json"}
            _LOGGER.debug("Harvia REST REQ %s %s params=%s body=%s", method, url, params, json_body)

            async with self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                _LOGGER.debug("Harvia REST RESP %s %s body=%s", resp.status, url, text)

                if resp.status < 400:
                    return json.loads(text) if text else {}

                if resp.status in (401, 403) and attempt == 0:
                    continue

                if resp.status in (401, 403):
                    raise HarviaAuthError(f"Unauthorized ({resp.status}) for {url}: {text}")

                raise RuntimeError(f"{method} {url} failed {resp.status}: {text}")

        raise HarviaAuthError(f"Unauthorized after retry for {url}")

    # -----------------------------
    # Devices
    # -----------------------------

    async def get_devices(self) -> list[HarviaDevice]:
        await self.async_init()
        assert self._rest_device_base is not None

        data = await self.rest_call(self._rest_device_base, "GET", "/devices")
        devices_raw = data.get("devices") if isinstance(data, dict) else data

        if not isinstance(devices_raw, list):
            _LOGGER.warning("Unexpected /devices format: %s", data)
            return []

        out: list[HarviaDevice] = []
        for item in devices_raw:
            if not isinstance(item, dict):
                continue

            # Harvia uses "name" as identifier -> map to id
            device_id = str(item.get("id") or item.get("deviceId") or item.get("name") or "")
            if not device_id:
                continue

            out.append(
                HarviaDevice(
                    id=device_id,
                    type=str(item.get("type") or ""),
                    name=str(item.get("name") or device_id),
                    attr=item.get("attr") or item.get("attributes") or [],
                    state=None,
                )
            )

        _LOGGER.info("Harvia devices discovered: %d", len(out))
        return out

    # -----------------------------
    # State normalization (as in your snippet)
    # -----------------------------

    def _extract_state(self, obj: dict[str, Any]) -> dict[str, Any]:
        """Normalize /devices/state payload into the flat dict your HA entities use.

        For these values we prefer the active profile values, with fallback to root state:
          - target_temperature, humidity_setpoint
          - heater_on_raw, steamer_on_raw, light_on_raw
        We keep *_state fields (heater_state/steamer_state) from root because they represent actual runtime state.
        """
        st = obj.get("state") or {}
        conn = obj.get("connectionState") or {}

        settings = st.get("settings") or {}
        screen_lock = st.get("screenLock") or {}
        heater = st.get("heater") or {}
        steamer = st.get("steamer") or {}
        light = st.get("light") or {}

        # ---- Active profile resolution (profiles keys are strings) ----
        active_profile = st.get("activeProfile")
        raw_profiles = st.get("profiles") or {}

        active_profile_dict = None
        try:
            ap_key = str(int(active_profile))
            if isinstance(raw_profiles, dict):
                active_profile_dict = raw_profiles.get(ap_key)
        except Exception:
            active_profile_dict = None

        # Profile-based values (preferred)
        profile_target_temp = None
        profile_target_hum = None
        profile_heater_on = None
        profile_steamer_on = None
        profile_light_on = None

        if isinstance(active_profile_dict, dict):
            profile_target_temp = active_profile_dict.get("targetTemp")
            profile_target_hum = active_profile_dict.get("targetHum")

            heater_p = active_profile_dict.get("heater") or {}
            steamer_p = active_profile_dict.get("steamer") or {}
            light_p = active_profile_dict.get("light") or {}

            if isinstance(heater_p, dict):
                profile_heater_on = heater_p.get("on")
            if isinstance(steamer_p, dict):
                profile_steamer_on = steamer_p.get("on")
            if isinstance(light_p, dict):
                profile_light_on = light_p.get("on")

        # Keep profiles (normalized) for Select/Number UI
        norm_profiles: dict[str, dict[str, Any]] = {}
        if isinstance(raw_profiles, dict):
            for k, p in raw_profiles.items():
                if not isinstance(p, dict):
                    continue
                norm_profiles[str(k)] = {
                    "name": p.get("name"),
                    "targetTemp": p.get("targetTemp"),
                    "targetHum": p.get("targetHum"),
                    "duration": p.get("duration"),
                    "heater_on": (p.get("heater") or {}).get("on") if isinstance(p.get("heater"), dict) else None,
                    "steamer_on": (p.get("steamer") or {}).get("on") if isinstance(p.get("steamer"), dict) else None,
                    "light_on": (p.get("light") or {}).get("on") if isinstance(p.get("light"), dict) else None,
                }

        normalized: dict[str, Any] = {
            "connected": conn.get("connected") if isinstance(conn, dict) else None,

            "display_name": st.get("displayName"),

            # Targets prefer profile
            "target_temperature": profile_target_temp if profile_target_temp is not None else st.get("targetTemp"),
            "humidity_setpoint": profile_target_hum if profile_target_hum is not None else st.get("targetHum"),

            # Desired state prefer profile; actual state remains root
            "heater_on_raw": profile_heater_on if profile_heater_on is not None else heater.get("on"),
            "heater_state": heater.get("state"),

            "steamer_on_raw": profile_steamer_on if profile_steamer_on is not None else steamer.get("on"),
            "steamer_state": steamer.get("state"),

            "light_on_raw": profile_light_on if profile_light_on is not None else light.get("on"),

            "screen_lock_on": screen_lock.get("on"),

            "setting_max_on_time": settings.get("maxOnTime"),
            "setting_max_temp": settings.get("maxTemp"),
            "setting_temp_calibration": settings.get("tempCalibration"),
            "setting_blackout_control": settings.get("blackoutControl"),
            "setting_dehumidification": settings.get("dehumidification"),
            "setting_remote_control": settings.get("remoteControl"),
            "setting_screen_saver_time": settings.get("screenSaverTime"),
            "setting_lock_settings": settings.get("lockSettings"),
            "setting_lock_additional": settings.get("lockAdditional"),

            "remote_allowed": st.get("remoteAllowed"),
            "demo_mode": st.get("demoMode"),
            "active_profile": st.get("activeProfile"),
            "sauna_status": st.get("saunaStatus"),

            "profiles": norm_profiles,
        }
        return normalized

    async def refresh_device_state(self, device: HarviaDevice) -> dict[str, Any]:
        """Fetch /devices/state for this device, normalize, store in device.state and return it."""
        await self.async_init()
        assert self._rest_device_base is not None

        raw = await self.rest_call(
            self._rest_device_base,
            "GET",
            "/devices/state",
            params={"deviceId": device.id},
        )

        if isinstance(raw, dict):
            device.state = self._extract_state(raw)
        else:
            device.state = {}

        return device.state





