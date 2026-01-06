from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import HarviaSaunaAPI
from .coordinator import HarviaCoordinator
from .constants import DOMAIN, DATA_COORDINATOR, CONF_ENDPOINTS_URL, DEFAULT_ENDPOINTS_URL

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "binary_sensor"]


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change (poll intervals)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    username = entry.data["username"]
    password = entry.data["password"]
    endpoints_url = entry.data.get(CONF_ENDPOINTS_URL, DEFAULT_ENDPOINTS_URL)

    api = HarviaSaunaAPI(hass, username=username, password=password, endpoints_url=endpoints_url)
    coordinator = HarviaCoordinator(hass, entry, api)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        DATA_COORDINATOR: coordinator,
    }

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        api: HarviaSaunaAPI = hass.data[DOMAIN][entry.entry_id]["api"]
        await api.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
