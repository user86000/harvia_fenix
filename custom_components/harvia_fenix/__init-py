from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import HarviaSaunaAPI
from .coordinator import HarviaDataUpdateCoordinator
from .constants import DOMAIN, _LOGGER

# door/binary_sensor ist entfernt
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Harvia Fenix from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    username = entry.data.get("username")
    password = entry.data.get("password")
    if not username or not password:
        _LOGGER.error("Harvia: missing username/password in config entry")
        return False

    api = HarviaSaunaAPI(username=username, password=password, hass=hass)
    devices = await api.get_devices()

    coordinator = HarviaDataUpdateCoordinator(hass=hass, api=api, devices=devices)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "devices": devices,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            hass.data.pop(DOMAIN, None)
    return unload_ok


