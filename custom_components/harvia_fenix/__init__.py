from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import HarviaSaunaAPI
from .constants import DOMAIN, PLATFORMS, DATA_API, DATA_COORDINATOR, CONF_ENDPOINTS_URL, DEFAULT_ENDPOINTS_URL
from .coordinator import HarviaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    username = entry.data.get("username") or entry.data.get("email") or entry.data.get("user")
    password = entry.data.get("password")
    endpoints_url = entry.data.get(CONF_ENDPOINTS_URL, DEFAULT_ENDPOINTS_URL)

    api = HarviaSaunaAPI(hass, username=username, password=password, endpoints_url=endpoints_url)
    coordinator = HarviaCoordinator(hass, api)

    # First refresh
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_API: api,
        DATA_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data and data.get(DATA_API):
            await data[DATA_API].close()

    return unload_ok





