from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .constants import DOMAIN, DATA_COORDINATOR
from .coordinator import HarviaCoordinator
from .api import HarviaDevice


@dataclass(frozen=True)
class HarviaSensorSpec:
    key: str
    name: str
    unit: Optional[str]
    value_fn: Callable[[dict[str, Any]], Any]


def _get(state: dict[str, Any], key: str) -> Any:
    return state.get(key) if isinstance(state, dict) else None


SPECS: list[HarviaSensorSpec] = [
    HarviaSensorSpec("connected", "Connected", None, lambda s: _get(s, "connected")),
    HarviaSensorSpec("display_name", "Display Name", None, lambda s: _get(s, "display_name")),

    HarviaSensorSpec("target_temperature", "Target Temperature", UnitOfTemperature.CELSIUS, lambda s: _get(s, "target_temperature")),
    HarviaSensorSpec("humidity_setpoint", "Humidity Setpoint", PERCENTAGE, lambda s: _get(s, "humidity_setpoint")),

    HarviaSensorSpec("heater_on_raw", "Heater On (Requested)", None, lambda s: _get(s, "heater_on_raw")),
    HarviaSensorSpec("heater_state", "Heater State (Actual)", None, lambda s: _get(s, "heater_state")),

    HarviaSensorSpec("steamer_on_raw", "Steamer On (Requested)", None, lambda s: _get(s, "steamer_on_raw")),
    HarviaSensorSpec("steamer_state", "Steamer State (Actual)", None, lambda s: _get(s, "steamer_state")),

    HarviaSensorSpec("light_on_raw", "Light On (Requested)", None, lambda s: _get(s, "light_on_raw")),
    HarviaSensorSpec("screen_lock_on", "Screen Lock", None, lambda s: _get(s, "screen_lock_on")),

    HarviaSensorSpec("setting_max_on_time", "Setting Max On Time", None, lambda s: _get(s, "setting_max_on_time")),
    HarviaSensorSpec("setting_max_temp", "Setting Max Temp", UnitOfTemperature.CELSIUS, lambda s: _get(s, "setting_max_temp")),
    HarviaSensorSpec("setting_temp_calibration", "Setting Temp Calibration", None, lambda s: _get(s, "setting_temp_calibration")),
    HarviaSensorSpec("setting_blackout_control", "Setting Blackout Control", None, lambda s: _get(s, "setting_blackout_control")),
    HarviaSensorSpec("setting_dehumidification", "Setting Dehumidification", None, lambda s: _get(s, "setting_dehumidification")),
    HarviaSensorSpec("setting_remote_control", "Setting Remote Control", None, lambda s: _get(s, "setting_remote_control")),
    HarviaSensorSpec("setting_screen_saver_time", "Setting Screen Saver Time", None, lambda s: _get(s, "setting_screen_saver_time")),
    HarviaSensorSpec("setting_lock_settings", "Setting Lock Settings", None, lambda s: _get(s, "setting_lock_settings")),
    HarviaSensorSpec("setting_lock_additional", "Setting Lock Additional", None, lambda s: _get(s, "setting_lock_additional")),

    HarviaSensorSpec("remote_allowed", "Remote Allowed", None, lambda s: _get(s, "remote_allowed")),
    HarviaSensorSpec("demo_mode", "Demo Mode", None, lambda s: _get(s, "demo_mode")),

    # We'll attach profiles as attributes on this one:
    HarviaSensorSpec("active_profile", "Active Profile", None, lambda s: _get(s, "active_profile")),

    HarviaSensorSpec("sauna_status", "Sauna Status", None, lambda s: _get(s, "sauna_status")),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HarviaCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    devices: list[HarviaDevice] = coordinator.data.get("devices", [])
    entities: list[SensorEntity] = []

    for dev in devices:
        for spec in SPECS:
            entities.append(HarviaStateSensor(coordinator, dev, spec))

    async_add_entities(entities)


class HarviaStateSensor(CoordinatorEntity[HarviaCoordinator], SensorEntity):
    def __init__(self, coordinator: HarviaCoordinator, device: HarviaDevice, spec: HarviaSensorSpec) -> None:
        super().__init__(coordinator)
        self._device = device
        self._spec = spec

        self._attr_unique_id = f"{device.id}_{spec.key}"
        self._attr_name = f"Harvia {device.type} {spec.name}"

        if spec.unit:
            self._attr_native_unit_of_measurement = spec.unit

        self._attr_device_info = {
            "identifiers": {(DOMAIN, device.id)},
            "name": f"Harvia {device.type}",
            "manufacturer": "Harvia",
            "model": device.type,
        }

    @property
    def native_value(self) -> Any:
        states = self.coordinator.data.get("states", {})
        state = states.get(self._device.id)
        if not isinstance(state, dict):
            return None
        return self._spec.value_fn(state)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        # Only add bulky attributes once (on "Active Profile")
        if self._spec.key != "active_profile":
            return None

        states = self.coordinator.data.get("states", {})
        state = states.get(self._device.id)
        if not isinstance(state, dict):
            return None

        # expose profiles and a few helpful context fields
        return {
            "profiles": state.get("profiles"),
            "display_name": state.get("display_name"),
            "target_temperature": state.get("target_temperature"),
            "humidity_setpoint": state.get("humidity_setpoint"),
        }



