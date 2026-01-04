from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HarviaSaunaAPI, HarviaDevice, HarviaAuthError
from .constants import (
    CONF_DATA_POLL_INTERVAL,
    CONF_DEVICE_POLL_INTERVAL,
    POLL_INTERVAL_OPTIONS,
    DEFAULT_DATA_POLL_LABEL,
    DEFAULT_DEVICE_POLL_LABEL,
)

_LOGGER = logging.getLogger(__name__)


def _parse_interval(value: Any, default_label: str) -> int:
    """Accept either label ('30s') or int seconds."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        return int(POLL_INTERVAL_OPTIONS.get(value, POLL_INTERVAL_OPTIONS[default_label]))
    return int(POLL_INTERVAL_OPTIONS[default_label])


class HarviaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: HarviaSaunaAPI) -> None:
        self.api = api

        self._data_interval = _parse_interval(
            entry.options.get(CONF_DATA_POLL_INTERVAL, DEFAULT_DATA_POLL_LABEL),
            DEFAULT_DATA_POLL_LABEL,
        )
        self._device_interval = _parse_interval(
            entry.options.get(CONF_DEVICE_POLL_INTERVAL, DEFAULT_DEVICE_POLL_LABEL),
            DEFAULT_DEVICE_POLL_LABEL,
        )

        super().__init__(
            hass,
            _LOGGER,
            name="harvia_fenix",
            update_interval=timedelta(seconds=self._data_interval),
        )

        self._last_device_refresh: float = 0.0
        self._last_data_refresh: float = 0.0

        self._devices: list[HarviaDevice] = []
        self._states: dict[str, Any] = {}
        self._latest_data: dict[str, Any] = {}

        _LOGGER.info(
            "Harvia polling configured: data=%ss device/state=%ss",
            self._data_interval,
            self._device_interval,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        now = time.monotonic()

        try:
            if (not self._devices) or (now - self._last_device_refresh) >= self._device_interval:
                _LOGGER.debug("Harvia: refreshing devices/state (interval=%ss)", self._device_interval)
                self._devices = await self.api.get_devices()
                for dev in self._devices:
                    self._states[dev.id] = await self.api.refresh_device_state(dev)
                self._last_device_refresh = now
            else:
                _LOGGER.debug("Harvia: skipping devices/state (cached)")

            if (now - self._last_data_refresh) >= self._data_interval:
                _LOGGER.debug("Harvia: refreshing latest-data (interval=%ss)", self._data_interval)
                for dev in self._devices:
                    try:
                        self._latest_data[dev.id] = await self.api.get_latest_data(dev)
                    except Exception as err:
                        _LOGGER.debug("Harvia latest-data failed for %s: %s", dev.id, err)
                self._last_data_refresh = now
            else:
                _LOGGER.debug("Harvia: skipping latest-data (cached)")

            return {
                "devices": self._devices,
                "states": self._states,
                "latest_data": self._latest_data,
            }

        except HarviaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(f"Harvia update failed: {err}") from err
