from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_ENDPOINTS_URL = "https://api.harvia.io/endpoints"


@dataclass
class HarviaTokens:
    id_token: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None


@dataclass
class HarviaDevice:
    id: str
    type: str
    name: str
    attr: list[dict[str, Any]]
    state: dict[str, Any] | None = None


class HarviaSaunaAPI:
    """Harvia REST API client used by the HA integration."""

    def __init__(self, username: str, password: str, hass: Any | None = None) -> None:
        self._username = username
        self._password = password
        self._hass = hass

        self._session: aiohttp.ClientSession | None = None
        self._tokens = HarviaTokens()

        self._endpoints_loaded = False
        self._rest_generics_base: str | None = None
        self._rest_device_base: str | None = None

    # -------------------------
    # Lifecycle / init
    # -------------------------

    async def async_init(self) -> None:
        """Ensure session + endpoints + auth tokens. Hard-fails if endpoints are missing."""
        if self._session is None:
            self._session = aiohttp.ClientSession()

        if not self._endpoints_loaded:
            await self._load_endpoints()

        if not self._rest_generics_base or not self._rest_device_base:
            raise RuntimeError(
                f"Harvia endpoints not initialized "
                f"(generics={self._rest_generics_base}, device={self._rest_device_base})"
            )

        # device API requires idToken (accessToken is explicitly denied in policy)
        if not self._tokens.id_token and not self._tokens.access_token:
            await self._authenticate()

        if not self._tokens.id_token:
            raise RuntimeError("Harvia authentication did not return idToken; cannot call device API")

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
        self._session = None

    async def _ensure_session_and_endpoints(self) -> None:
        """Ensure session + endpoints WITHOUT triggering authentication (prevents recursion)."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        if not self._endpoints_loaded:
            await self._load_endpoints()

        if not self._rest_generics_base or not self._rest_device_base:
            raise RuntimeError(
                f"Harvia endpoints not initialized "
                f"(generics={self._rest_generics_base}, device={self._rest_device_base})"
            )

    async def _load_endpoints(self) -> None:
        """Load REST endpoints from Harvia endpoints service.

        Supports both:
        - legacy: {"generics": "...", "device": "..."}
        - new:    {"endpoints":{"RestApi":{"generics":{"https":"..."},"device":{"https":"..."}}}}
        """
        assert self._session is not None

        _LOGGER.info("Harvia: loading endpoints from %s", DEFAULT_ENDPOINTS_URL)

        async with self._session.get(
            DEFAULT_ENDPOINTS_URL,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"Accept": "application/json"},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        _LOGGER.debug("Harvia endpoints raw payload: %s", data)

        rest_api = (data.get("endpoints") or {}).get("RestApi") or {}

        generics = (
            (rest_api.get("generics") or {}).get("https")
            or data.get("generics")
        )
        device = (
            (rest_api.get("device") or {}).get("https")
            or data.get("device")
        )

        if not generics or not device:
            raise RuntimeError(f"Invalid endpoints payload (no generics/device found): {data}")

        self._rest_generics_base = str(generics).rstrip("/")
        self._rest_device_base = str(device).rstrip("/")
        self._endpoints_loaded = True

        _LOGGER.info(
            "Harvia: endpoints loaded generics=%s device=%s",
            self._rest_generics_base,
            self._rest_device_base,
        )

    async def _authenticate(self) -> None:
        """Authenticate via generics gateway (/auth/token)."""
        await self._ensure_session_and_endpoints()
        assert self._session is not None
        assert self._rest_generics_base is not None

        url = f"{self._rest_generics_base}/auth/token"
        payload = {"username": self._username, "password": self._password}

        _LOGGER.debug("Harvia AUTH TRY url=%s user=%s", url, self._username)

        async with self._session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"Accept": "application/json"},
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Auth failed {resp.status}: {text}")

            try:
                data = json.loads(text) if text else {}
            except Exception:
                data = await resp.json()

        self._tokens.id_token = data.get("idToken") or data.get("id_token")
        self._tokens.access_token = data.get("accessToken") or data.get("access_token")
        self._tokens.refresh_token = data.get("refreshToken") or data.get("refresh_token")

        expires_in = data.get("expiresIn") or data.get("expires_in")
        if expires_in:
            try:
                self._tokens.expires_at = time.time() + float(expires_in)
            except Exception:
                self._tokens.expires_at = None

        _LOGGER.debug(
            "Harvia tokens received: access=%s id=%s refresh=%s",
            bool(self._tokens.access_token),
            bool(self._tokens.id_token),
            bool(self._tokens.refresh_token),
        )

        _LOGGER.info("Harvia auth OK (idToken present=%s)", bool(self._tokens.id_token))

    # -------------------------
    # REST
    # -------------------------

    def _token_candidates_for_base(self, base: str) -> list[tuple[str, Optional[str]]]:
        """Device API: force id token. Others: access then id."""
        if self._rest_device_base and base.rstrip("/") == self._rest_device_base.rstrip("/"):
            return [("id", self._tokens.id_token)]
        return [
            ("access", self._tokens.access_token),
            ("id", self._tokens.id_token),
        ]

    async def rest_call(
        self,
        base: str,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        await self.async_init()
        assert self._session is not None

        if not base:
            raise RuntimeError("Harvia rest_call called with empty base URL (base is None/empty)")

        url = f"{base.rstrip('/')}/{path.lstrip('/')}"
        timeout = aiohttp.ClientTimeout(total=30)

        token_candidates = self._token_candidates_for_base(base)

        last_status: int | None = None
        last_text: str | None = None

        for token_type, token in token_candidates:
            if not token:
                continue

            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            }

            _LOGGER.debug("Harvia REST REQ %s %s token=%s params=%s", method, url, token_type, params)

            async with self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=timeout,
            ) as resp:
                text = await resp.text()
                _LOGGER.debug("Harvia REST RESP %s %s token=%s body=%s", resp.status, url, token_type, text)

                if resp.status < 400:
                    if not text:
                        return {}
                    try:
                        return json.loads(text)
                    except Exception:
                        return await resp.json()

                last_status = resp.status
                last_text = text

                if resp.status in (401, 403):
                    continue

                raise RuntimeError(f"REST {method} {url} failed {resp.status}: {text}")

        raise RuntimeError(f"REST {method} {url} failed {last_status}: {last_text}")

    # -------------------------
    # Public API used by HA
    # -------------------------

    async def get_devices(self) -> list[HarviaDevice]:
        """Fetch devices list from /devices and return HarviaDevice objects."""
        await self.async_init()
        assert self._rest_device_base is not None

        data = await self.rest_call(self._rest_device_base, "GET", "/devices")
        devices = data.get("devices", []) if isinstance(data, dict) else []

        out: list[HarviaDevice] = []
        for d in devices:
            if not isinstance(d, dict):
                continue

            dev_id = str(d.get("name") or d.get("id") or "")
            if not dev_id:
                continue

            out.append(
                HarviaDevice(
                    id=dev_id,
                    type=str(d.get("type") or ""),
                    name=str(d.get("name") or d.get("id") or dev_id),
                    attr=d.get("attr", []) or [],
                    state={},
                )
            )

        _LOGGER.info("Harvia: discovered %s devices via REST /devices", len(out))
        return out

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

            # Heater/Steamer/Light desired state prefer profile; actual state remains root
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

    async def set_device_target(self, device_id: str, payload: dict[str, Any]) -> None:
        """Best-effort setter (activeProfile etc.)."""
        await self.async_init()
        assert self._rest_device_base is not None

        candidates = [
            ("POST", "/devices/target", {"deviceId": device_id, **payload}),
            ("POST", "/devices/target", {"deviceId": device_id, "state": payload}),
            ("PUT", "/devices/state", {"deviceId": device_id, "state": payload}),
        ]

        last_err: Exception | None = None
        for method, path, body in candidates:
            try:
                await self.rest_call(self._rest_device_base, method, path, json_body=body)
                return
            except Exception as e:
                last_err = e

        raise last_err or RuntimeError("Failed to set device target")
