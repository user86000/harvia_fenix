from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import HarviaSaunaAPI
from .constants import DOMAIN, CONF_ENDPOINTS_URL, DEFAULT_ENDPOINTS_URL

from .coordinator import HarviaDeviceCoordinator, HarviaDataCoordinator
from .constants import DEVICE_COORDINATOR, DATA_COORDINATOR

from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "binary_sensor", "switch"]


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change (poll intervals)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    username = entry.data["username"]
    password = entry.data["password"]
    endpoints_url = entry.data.get(CONF_ENDPOINTS_URL, DEFAULT_ENDPOINTS_URL)

    api = HarviaSaunaAPI(hass, username=username, password=password, endpoints_url=endpoints_url)

    device_coordinator = HarviaDeviceCoordinator(hass, entry, api)
    data_coordinator = HarviaDataCoordinator(hass, entry, api, device_coordinator)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        DEVICE_COORDINATOR: device_coordinator,
        DATA_COORDINATOR: data_coordinator,
    }

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await device_coordinator.async_config_entry_first_refresh()
    await data_coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        api: HarviaSaunaAPI = hass.data[DOMAIN][entry.entry_id]["api"]
        await api.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok

# Service

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def handle_revoke_tokens(call: ServiceCall) -> None:
        domain_data = hass.data.get(DOMAIN, {})
        if not domain_data:
            raise HomeAssistantError("No Harvia Fenix entries loaded")

        any_called = False
        for entry_id, store in domain_data.items():
            api = store.get("api")
            if api is None:
                continue

            # nutzt deine neue API-Methode
            ok = await api.async_revoke_tokens()
            any_called = True

            if not ok:
                raise HomeAssistantError(f"Token revoke failed for entry {entry_id}")

        if not any_called:
            raise HomeAssistantError("Harvia API not initialized")

    hass.services.async_register(
        DOMAIN,
        "revoke_tokens",
        handle_revoke_tokens,
    )

    return True
