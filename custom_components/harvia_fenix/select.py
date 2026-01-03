from __future__ import annotations

from typing import Any, Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .constants import DOMAIN
from .coordinator import HarviaDataUpdateCoordinator


def _attrs_to_dict(device: Any) -> dict[str, Any]:
    raw = getattr(device, "attr", None)
    if isinstance(raw, list):
        out: dict[str, Any] = {}
        for item in raw:
            k = item.get("key")
            v = item.get("value")
            if k:
                out[k] = v
        return out
    if isinstance(raw, dict):
        return raw
    return {}


def _serial(device: Any) -> str:
    attrs = _attrs_to_dict(device)
    v = attrs.get("serialNumber") or attrs.get("serial_number")
    if v:
        return str(v)
    return str(getattr(device, "id", getattr(device, "name", "unknown")))


def _device_info(device: Any) -> DeviceInfo:
    attrs = _attrs_to_dict(device)
    serial = _serial(device)
    model = getattr(device, "type", None) or attrs.get("panelType") or "Fenix"
    sw = attrs.get("powerUnitFwVersion") or attrs.get("initialFirmware")
    return DeviceInfo(
        identifiers={(DOMAIN, serial)},
        name=f"Harvia {serial}",
        manufacturer="Harvia",
        model=str(model),
        sw_version=str(sw) if sw else None,
    )


def _as_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HarviaDataUpdateCoordinator = data["coordinator"]
    devices = data["devices"]

    async_add_entities([HarviaActiveProfileSelect(coordinator, d) for d in devices])


class HarviaActiveProfileSelect(CoordinatorEntity, SelectEntity):
    def __init__(self, coordinator: HarviaDataUpdateCoordinator, device: Any) -> None:
        super().__init__(coordinator)
        self._device = device
        self._serial = _serial(device)
        self._dev_id = str(getattr(device, "id", None) or getattr(device, "name", None) or "unknown")

        self._attr_device_info = _device_info(device)
        self._attr_has_entity_name = True
        self._attr_name = "Active Profile"
        self._attr_unique_id = f"{self._serial}_active_profile_select"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:playlist-check"

    def _state(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        st = data.get(self._dev_id)
        if isinstance(st, dict) and st:
            return st
        st2 = getattr(self._device, "state", None)
        return st2 if isinstance(st2, dict) else {}

    @property
    def options(self) -> list[str]:
        st = self._state()
        profiles = st.get("profiles")
        if isinstance(profiles, list) and profiles:
            opts: list[str] = []
            for i, p in enumerate(profiles):
                if isinstance(p, dict):
                    name = p.get("name") or p.get("profileName") or f"Profile {i}"
                else:
                    name = f"Profile {i}"
                opts.append(str(name))
            return opts

        return ["Profile 0", "Profile 1", "Profile 2", "Profile 3"]

    @property
    def current_option(self) -> Optional[str]:
        idx = _as_int(self._state().get("active_profile"))
        if idx is None:
            return None
        opts = self.options
        return opts[idx] if 0 <= idx < len(opts) else None

    async def async_select_option(self, option: str) -> None:
        opts = self.options
        if option not in opts:
            raise ValueError(f"Invalid option: {option}")

        idx = opts.index(option)
        await self._async_set_active_profile(idx)

        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def _async_set_active_profile(self, idx: int) -> None:
        api = self.coordinator.api
        device_id = self._dev_id
        payload = {"activeProfile": idx}

        if hasattr(api, "set_device_target"):
            await api.set_device_target(device_id, payload)
            return
        if hasattr(api, "set_active_profile"):
            await api.set_active_profile(device_id, idx)
            return
        if hasattr(api, "set_device_state"):
            await api.set_device_state(device_id, payload)
            return

        raise RuntimeError(
            "No suitable API method found to set active profile. "
            "Implement one of: set_device_target(device_id, payload), "
            "set_active_profile(device_id, idx), set_device_state(device_id, payload)."
        )


