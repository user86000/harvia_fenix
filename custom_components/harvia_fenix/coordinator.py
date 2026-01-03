from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HarviaSaunaAPI, HarviaDevice, HarviaAuthError

_LOGGER = logging.getLogger(__name__)

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=30)


class HarviaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """coordinator.data:
    {
      "devices": list[HarviaDevice],
      "states": { "<device_id>": <normalized_flat_state_dict> }
    }
    """

    def __init__(self, hass: HomeAssistant, api: HarviaSaunaAPI) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="harvia_fenix",
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            devices: list[HarviaDevice] = await self.api.get_devices()
            states: dict[str, Any] = {}

            for dev in devices:
                states[dev.id] = await self.api.refresh_device_state(dev)

            return {"devices": devices, "states": states}

        except HarviaAuthError as err:
            # triggers HA reauth flow
            raise ConfigEntryAuthFailed(str(err)) from err

        except Exception as err:
            raise UpdateFailed(f"Harvia update failed: {err}") from err


