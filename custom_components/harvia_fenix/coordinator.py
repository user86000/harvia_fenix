from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import HarviaFenixApi, HarviaDevice, HarviaAuthError, HarviaApiError

_LOGGER = logging.getLogger(__name__)


class HarviaFenixCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: HarviaFenixApi,
        device_poll_interval_s: int,
        data_poll_interval_s: int,
    ) -> None:
        # Wir triggern Updates über async_refresh selbst/extern – aber der Coordinator braucht ein update_interval.
        # Nimm hier den kleineren der beiden Intervalle, damit es “oft genug” läuft.
        update_interval_s = max(10, min(int(device_poll_interval_s), int(data_poll_interval_s)))

        super().__init__(
            hass,
            _LOGGER,
            name="harvia_fenix",
            update_interval=None,  # wir steuern das in _async_update_data selbst über timeouts/HA scheduler nicht
        )

        self.api = api
        self.device_poll_interval_s = int(device_poll_interval_s)
        self.data_poll_interval_s = int(data_poll_interval_s)

        self._devices: dict[str, HarviaDevice] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._latest: dict[str, dict[str, Any]] = {}

    @property
    def devices(self) -> dict[str, HarviaDevice]:
        return self._devices

    @property
    def states(self) -> dict[str, dict[str, Any]]:
        return self._states

    @property
    def latest(self) -> dict[str, dict[str, Any]]:
        return self._latest

    async def _try_state_with_fallback(self, dev: HarviaDevice) -> dict[str, Any] | None:
        """Try state endpoint with device UUID; if 403 -> retry with serialNumber."""
        try_ids: list[str] = [dev.id]

        if dev.attrs:
            serial = dev.attrs.get("serialNumber")
            if serial and str(serial) not in try_ids:
                try_ids.append(str(serial))

        last_err: Exception | None = None
        for did in try_ids:
            try:
                return await self.api.get_device_state(did)
            except HarviaAuthError as err:
                # 401 => auth issue
                raise err
            except HarviaApiError as err:
                # If forbidden for the first ID, try next; otherwise keep last error
                last_err = err
                continue
            except Exception as err:
                last_err = err
                continue

        if last_err:
            _LOGGER.warning("State fetch failed for %s (tried %s): %s", dev.id, try_ids, last_err)
        return None

    async def _try_latest_with_fallback(self, dev: HarviaDevice) -> dict[str, Any] | None:
        """Try latest-data endpoint with device UUID; if 403 -> retry with serialNumber."""
        try_ids: list[str] = [dev.id]

        if dev.attrs:
            serial = dev.attrs.get("serialNumber")
            if serial and str(serial) not in try_ids:
                try_ids.append(str(serial))

        last_err: Exception | None = None
        for did in try_ids:
            try:
                return await self.api.get_latest_data(did)
            except HarviaAuthError as err:
                raise err
            except HarviaApiError as err:
                last_err = err
                continue
            except Exception as err:
                last_err = err
                continue

        if last_err:
            _LOGGER.warning("Latest-data fetch failed for %s (tried %s): %s", dev.id, try_ids, last_err)
        return None

    async def _async_update_data(self) -> dict[str, Any]:
        """
        IMPORTANT:
        - 401 => ConfigEntryAuthFailed (reauth)
        - 403 or other API errors => log + continue (do not break setup)
        """
        try:
            devices = await self.api.get_devices()
        except HarviaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(f"Device list update failed: {err}") from err

        # Always store devices so integration works even if state/latest are blocked.
        self._devices = {d.id: d for d in devices}

        # Fetch state/latest per device, but NEVER fail the whole coordinator update on 403.
        new_states: dict[str, dict[str, Any]] = {}
        new_latest: dict[str, dict[str, Any]] = {}

        for dev in devices:
            # state
            try:
                state = await self._try_state_with_fallback(dev)
                if state is not None:
                    new_states[dev.id] = state
            except HarviaAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except Exception as err:
                _LOGGER.warning("State update error for %s: %s", dev.id, err)

            # latest-data
            try:
                latest = await self._try_latest_with_fallback(dev)
                if latest is not None:
                    new_latest[dev.id] = latest
            except HarviaAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except Exception as err:
                _LOGGER.warning("Latest-data update error for %s: %s", dev.id, err)

        self._states = new_states
        self._latest = new_latest

        # Return one combined structure for entities
        return {
            "devices": self._devices,
            "states": self._states,
            "latest": self._latest,
        }


