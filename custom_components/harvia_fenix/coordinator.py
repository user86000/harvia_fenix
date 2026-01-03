from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .constants import DOMAIN, _LOGGER


class HarviaDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Central poller for all Harvia devices."""

    def __init__(self, hass: HomeAssistant, api: Any, devices: list[Any]) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.api = api
        self.devices = devices

    @staticmethod
    def _device_id(device: Any) -> str:
        return str(getattr(device, "id", None) or getattr(device, "name", None) or "unknown")

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            out: dict[str, dict[str, Any]] = {}

            for dev in self.devices:
                dev_id = self._device_id(dev)

                # Erwartung: api.refresh_device_state(dev) liefert den NORMALISIERTEN dict state
                state = await self.api.refresh_device_state(dev)

                # Robust: wenn die API nichts returned, aber dev.state setzt, nutzen wir das.
                if isinstance(state, dict):
                    try:
                        dev.state = state
                    except Exception:
                        pass
                    out[dev_id] = state
                else:
                    st = getattr(dev, "state", None)
                    out[dev_id] = st if isinstance(st, dict) else {}

            return out

        except Exception as err:
            raise UpdateFailed(f"Harvia update failed: {err}") from err
