from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfTemperature,
    PERCENTAGE,
    UnitOfTime,
    UnitOfPower,
)
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

# ---------------------------
# Helpers
# ---------------------------

def _get(state: dict[str, Any], key: str) -> Any:
    return state.get(key) if isinstance(state, dict) else None


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


# ---------------------------
# Base (state) sensors: /devices/state normalized dict
# ---------------------------

@dataclass(frozen=True)
class HarviaSensorSpec:
    key: str
    name: str
    unit: Optional[str]
    value_fn: Callable[[dict[str, Any]], Any]
    entity_category: EntityCategory | None = None
    with_attributes: bool = False  # control extra attrs per spec


STATE_SPECS: list[HarviaSensorSpec] = [
    HarviaSensorSpec("connected", "Connected", None, lambda s: _get(s, "connected")),
    HarviaSensorSpec("display_name", "Display Name", None, lambda s: _get(s, "display_name")),

    HarviaSensorSpec("target_temperature", "Target Temperature", UnitOfTemperature.CELSIUS, lambda s: _get(s, "target_temperature")),
    HarviaSensorSpec("humidity_setpoint", "Humidity Setpoint", PERCENTAGE, lambda s: _get(s, "humidity_setpoint")),

    HarviaSensorSpec("heater_on_raw", "Heater On (Requested)", None, lambda s: _get(s, "heater_on_raw")),
    HarviaSensorSpec("heater_state", "Heater State (Actual)", None, lambda s: _get(s, "heater_state")),

    HarviaSensorSpec("steamer_on_raw", "Steamer On (Requested)", None, lambda s: _get(s, "steamer_on_raw")),
    HarviaSensorSpec("steamer_state", "Steamer State (Actual)", None, lambda s: _get(s, "steamer_state")),

    HarviaSensorSpec("light_on_raw", "Light On (Requested)", None, lambda s: _get(s, "light_on_raw")),

    HarviaSensorSpec("screen_lock_on", "Screen Lock", None, lambda s: _get(s, "screen_lock_on"), EntityCategory.DIAGNOSTIC),

    # Settings -> Diagnose
    HarviaSensorSpec("setting_max_on_time", "Setting Max On Time", UnitOfTime.MINUTES, lambda s: _get(s, "setting_max_on_time"), EntityCategory.DIAGNOSTIC),
    HarviaSensorSpec("setting_max_temp", "Setting Max Temp", UnitOfTemperature.CELSIUS, lambda s: _get(s, "setting_max_temp"), EntityCategory.DIAGNOSTIC),
    HarviaSensorSpec("setting_temp_calibration", "Setting Temp Calibration", None, lambda s: _get(s, "setting_temp_calibration"), EntityCategory.DIAGNOSTIC),
    HarviaSensorSpec("setting_blackout_control", "Setting Blackout Control", None, lambda s: _get(s, "setting_blackout_control"), EntityCategory.DIAGNOSTIC),
    HarviaSensorSpec("setting_dehumidification", "Setting Dehumidification", None, lambda s: _get(s, "setting_dehumidification"), EntityCategory.DIAGNOSTIC),
    HarviaSensorSpec("setting_remote_control", "Setting Remote Control", None, lambda s: _get(s, "setting_remote_control"), EntityCategory.DIAGNOSTIC),

    # screen timeout / screensaver
    HarviaSensorSpec("setting_screen_saver_time", "Setting Screen Saver Time", UnitOfTime.SECONDS, lambda s: _get(s, "setting_screen_saver_time"), EntityCategory.DIAGNOSTIC),

    HarviaSensorSpec("setting_lock_settings", "Setting Lock Settings", None, lambda s: _get(s, "setting_lock_settings"), EntityCategory.DIAGNOSTIC),
    HarviaSensorSpec("setting_lock_additional", "Setting Lock Additional", None, lambda s: _get(s, "setting_lock_additional"), EntityCategory.DIAGNOSTIC),

    HarviaSensorSpec("remote_allowed", "Remote Allowed", None, lambda s: _get(s, "remote_allowed")),
    HarviaSensorSpec("demo_mode", "Demo Mode", None, lambda s: _get(s, "demo_mode"), EntityCategory.DIAGNOSTIC),

    HarviaSensorSpec("profiledata", "Profile Data", None, lambda s: _get(s, "active_profile"), with_attributes=True),
    HarviaSensorSpec("active_profile", "Active Profile", None, lambda s: _get(s, "active_profile"), with_attributes=False),

    HarviaSensorSpec("sauna_status", "Sauna Status", None, lambda s: _get(s, "sauna_status")),
]


# ---------------------------
# Data (telemetry) sensors: /data/latest-data "data" dict
# ---------------------------

@dataclass(frozen=True)
class HarviaDataSensorSpec:
    data_key: str
    name: str  # must include "data_" prefix
    unit: Optional[str] = None
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC
    disabled_by_default: bool = False


DATA_SPECS: list[HarviaDataSensorSpec] = [
    HarviaDataSensorSpec("heaterPower", "data_heaterPower", UnitOfPower.WATT),

    HarviaDataSensorSpec("extSensorTemp", "data_extSensorTemp", UnitOfTemperature.CELSIUS, disabled_by_default=True),
    HarviaDataSensorSpec("mainSensorTemp", "data_mainSensorTemp", UnitOfTemperature.CELSIUS, disabled_by_default=True),

    HarviaDataSensorSpec("temp", "data_temp", UnitOfTemperature.CELSIUS),
    HarviaDataSensorSpec("panelTemp", "data_panelTemp", UnitOfTemperature.CELSIUS),

    HarviaDataSensorSpec("hum", "data_hum", PERCENTAGE),
    HarviaDataSensorSpec("targetHum", "data_targetHum", PERCENTAGE),
    HarviaDataSensorSpec("targetTemp", "data_targetTemp", UnitOfTemperature.CELSIUS),

    HarviaDataSensorSpec("totalBathingHours", "data_totalBathingHours", UnitOfTime.HOURS),
    HarviaDataSensorSpec("totalHours", "data_totalHours", UnitOfTime.HOURS),
    HarviaDataSensorSpec("totalSessions", "data_totalSessions", None),

    HarviaDataSensorSpec("onTime", "data_onTime", UnitOfTime.MINUTES),
    HarviaDataSensorSpec("afterHeatTime", "data_afterHeatTime", UnitOfTime.MINUTES),
    HarviaDataSensorSpec("ontimeLT", "data_ontimeLT", UnitOfTime.MINUTES),
]


# ---------------------------
# Setup entry
# ---------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device_coordinator: HarviaDeviceCoordinator = hass.data[DOMAIN][entry.entry_id][DEVICE_COORDINATOR]
    data_coordinator: HarviaDataCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    devices: list[HarviaDevice] = (device_coordinator.data or {}).get("devices", [])
    entities: list[SensorEntity] = []

    for dev in devices:
        for spec in STATE_SPECS:
            entities.append(HarviaStateSensor(device_coordinator, dev, spec))

        for dspec in DATA_SPECS:
            entities.append(HarviaLatestDataSensor(data_coordinator, dev, dspec))

    async_add_entities(entities)


# ---------------------------
# Entities
# ---------------------------

class HarviaStateSensor(CoordinatorEntity[HarviaDeviceCoordinator], SensorEntity):
    def __init__(self, coordinator: HarviaDeviceCoordinator, device: HarviaDevice, spec: HarviaSensorSpec) -> None:
        super().__init__(coordinator)
        self._device = device
        self._spec = spec

        self._attr_unique_id = f"{device.id}_{spec.key}"
        self._attr_name = f"Harvia {device.type} {spec.name}"

        if spec.unit:
            self._attr_native_unit_of_measurement = spec.unit

        if spec.entity_category is not None:
            self._attr_entity_category = spec.entity_category

        self._attr_device_info = build_device_info(device)

    @property
    def native_value(self) -> Any:
        state = (self.coordinator.data or {}).get("states", {}).get(self._device.id)
        if not isinstance(state, dict):
            return None
        return self._spec.value_fn(state)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self._spec.with_attributes:
            return None

        state = (self.coordinator.data or {}).get("states", {}).get(self._device.id)
        if not isinstance(state, dict):
            return None

        return {
            "profiles": state.get("profiles"),
            "display_name": state.get("display_name"),
            "target_temperature": state.get("target_temperature"),
            "humidity_setpoint": state.get("humidity_setpoint"),
        }


class HarviaLatestDataSensor(CoordinatorEntity[HarviaDataCoordinator], SensorEntity):
    def __init__(self, coordinator: HarviaDataCoordinator, device: HarviaDevice, spec: HarviaDataSensorSpec) -> None:
        super().__init__(coordinator)
        self._device = device
        self._spec = spec

        self._attr_unique_id = f"{device.id}_{spec.name}"
        self._attr_name = f"Harvia {device.type} {spec.name}"

        if spec.disabled_by_default:
            self._attr_entity_registry_enabled_default = False

        if spec.unit:
            self._attr_native_unit_of_measurement = spec.unit

        if spec.entity_category is not None:
            self._attr_entity_category = spec.entity_category

        self._attr_device_info = build_device_info(device)

    @property
    def native_value(self) -> Any:
        data_dict = _get_latest_data_dict(self.coordinator, self._device.id)
        if not isinstance(data_dict, dict):
            return None
        return data_dict.get(self._spec.data_key)

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
