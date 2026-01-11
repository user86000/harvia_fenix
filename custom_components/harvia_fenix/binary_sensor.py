from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .constants import DOMAIN, DEVICE_COORDINATOR, DATA_COORDINATOR
from .coordinator import HarviaDeviceCoordinator, HarviaDataCoordinator
from .api import HarviaDevice

import inspect
from homeassistant.helpers import device_registry as dr

from .device_info import build_device_info


def _get_latest_payload(coordinator: HarviaDataCoordinator, device_id: str) -> dict[str, Any] | None:
    latest_map = coordinator.data.get("latest_data", {}) if coordinator.data else {}
    payload = latest_map.get(device_id)
    return payload if isinstance(payload, dict) else None


def _get_latest_data_dict(coordinator: HarviaDataCoordinator, device_id: str) -> dict[str, Any] | None:
    payload = _get_latest_payload(coordinator, device_id)
    if not isinstance(payload, dict):
        return None
    d = payload.get("data")
    return d if isinstance(d, dict) else None


@dataclass(frozen=True)
class HarviaDataBinarySpec:
    data_key: str
    name: str  # include "data_" prefix
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC
    disabled_by_default: bool = False


# Based on your response keys that are 0/1 or state-ish:
DATA_BINARY_SPECS: list[HarviaDataBinarySpec] = [
    HarviaDataBinarySpec("fanOn", "data_fanOn"),
    HarviaDataBinarySpec("steamOn", "data_steamOn"),
    HarviaDataBinarySpec("heatOn", "data_heatOn"),
    HarviaDataBinarySpec("lightOn", "data_lightOn"),

    HarviaDataBinarySpec("safetyRelay", "data_safetyRelay", EntityCategory.DIAGNOSTIC),
    HarviaDataBinarySpec("doorSafetyState", "data_doorSafetyState", EntityCategory.DIAGNOSTIC),

    HarviaDataBinarySpec("onOffTrigger", "data_onOffTrigger", EntityCategory.DIAGNOSTIC),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device_coordinator: HarviaDeviceCoordinator = hass.data[DOMAIN][entry.entry_id][DEVICE_COORDINATOR]
    data_coordinator: HarviaDataCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    devices: list[HarviaDevice] = (device_coordinator.data or {}).get("devices", [])

    entities: list[BinarySensorEntity] = []
    for dev in devices:
        for spec in DATA_BINARY_SPECS:
            entities.append(HarviaLatestDataBinarySensor(data_coordinator, dev, spec))

    async_add_entities(entities)


class HarviaLatestDataBinarySensor(CoordinatorEntity[HarviaDataCoordinator], BinarySensorEntity):
    """Binary telemetry from latest-data['data'] (static list DATA_BINARY_SPECS)."""

    def __init__(self, coordinator: HarviaDataCoordinator, device: HarviaDevice, spec: HarviaDataBinarySpec) -> None:
        super().__init__(coordinator)
        self._device = device
        self._spec = spec

        self._attr_unique_id = f"{device.id}_{spec.name}"
        self._attr_name = f"Harvia {device.type} {spec.name}"

        if spec.disabled_by_default:
            self._attr_entity_registry_enabled_default = False

        if spec.entity_category is not None:
            self._attr_entity_category = spec.entity_category

        self._attr_device_info = build_device_info(device)

    @property
    def is_on(self) -> Optional[bool]:
        data_dict = _get_latest_data_dict(self.coordinator, self._device.id)
        if not isinstance(data_dict, dict):
            return None

        val = data_dict.get(self._spec.data_key)

        # Treat 1/0, True/False, "1"/"0" as boolean
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(int(val))
        if isinstance(val, str):
            if val.strip() in ("1", "true", "True", "on", "ON"):
                return True
            if val.strip() in ("0", "false", "False", "off", "OFF"):
                return False

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        payload = _get_latest_payload(self.coordinator, self._device.id)
        if not isinstance(payload, dict):
            return None
        return {
            "timestamp": payload.get("timestamp"),
            "shadowName": payload.get("shadowName"),
            "subId": payload.get("subId"),
            "type": payload.get("type"),
        }
