from __future__ import annotations

from typing import Any, Optional

from homeassistant.components.number import NumberEntity, NumberMode
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

    async_add_entities([HarviaActiveProfileNumber(coordinator, d) for d in devices])


class HarviaActiveProfileNumber(CoordinatorEntity, NumberEntity):
    def __init__(self, coordinator: HarviaDataUpdateCoordinator, device: Any) -> None:
        super().__init__(coordinator)
        self._device = device
        self._serial = _serial(device)
        self._dev_id = str(getattr(device, "id", None) or getattr(device, "name", None) or "unknown")

        self._attr_device_info = _device_info(device)
        self._attr_has_entity_name = True
        self._attr_name = "Active Profile (Number)"
        self._attr_unique_id = f"{self._serial}_active_profile_number"

        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_mode = NumberMode.BOX
        self._attr_step = 1
        self._attr_native_min_value = 0
        self._attr_native_max_value = 3

    def _state(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        st = data.get(self._dev_id)
        if isinstance(st, dict) and st:
            return st
        st2 = getattr(self._device, "state", None)
        return st2 if isinstance(st2, dict) else {}

    def _update_min_max(self) -> None:
        st = self._state()
        profiles = st.get("profiles")
        if isinstance(profiles, list) and profiles:
            self._attr_native_min_value = 0
            self._attr_native_max_value = max(0, len(profiles) - 1)

    @property
    def native_value(self) -> Optional[float]:
        self._update_min_max()
        idx = _as_int(self._state().get("active_profile"))
        return float(idx) if idx is not None else None

    async def async_set_native_value(self, value: float) -> None:
        self._update_min_max()
        idx = int(value)

        if idx < int(self._attr_native_min_value) or idx > int(self._attr_native_max_value):
            raise ValueError(
                f"Active profile {idx} out of range "
                f"({self._attr_native_min_value}-{self._attr_native_max_value})"
            )

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

