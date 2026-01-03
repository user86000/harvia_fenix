from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .constants import DOMAIN
from .coordinator import HarviaDataUpdateCoordinator


# -------------------------
# Helpers
# -------------------------

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


def _device_name(device: Any) -> str:
    for attr_name in ("display_name", "displayName", "name"):
        v = getattr(device, attr_name, None)
        if v:
            return str(v)
    return f"Harvia {_serial(device)}"


def _device_info(device: Any) -> DeviceInfo:
    attrs = _attrs_to_dict(device)
    serial = _serial(device)
    model = getattr(device, "type", None) or attrs.get("panelType") or "Fenix"
    sw = attrs.get("powerUnitFwVersion") or attrs.get("initialFirmware")
    return DeviceInfo(
        identifiers={(DOMAIN, serial)},
        name=_device_name(device),
        manufacturer="Harvia",
        model=str(model),
        sw_version=str(sw) if sw else None,
    )


def _pick(state: dict[str, Any], key: str, default: Any = None) -> Any:
    return state.get(key, default)


def _as_bool(val: Any) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        v = val.strip().lower()
        if v in {"true", "1", "on", "yes"}:
            return True
        if v in {"false", "0", "off", "no"}:
            return False
    return None


def _as_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# -------------------------
# Entity descriptions
# -------------------------

@dataclass(frozen=True, kw_only=True)
class HarviaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


SENSOR_DESCRIPTIONS: tuple[HarviaSensorDescription, ...] = (
    # --- Core state ---
    HarviaSensorDescription(
        key="connected",
        name="Connected",
        icon="mdi:lan-connect",
        value_fn=lambda st: _as_bool(_pick(st, "connected")),
    ),
    HarviaSensorDescription(
        key="display_name",
        name="Display Name",
        icon="mdi:tag-text",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _pick(st, "display_name"),
    ),
    HarviaSensorDescription(
        key="sauna_status",
        name="Sauna Status",
        icon="mdi:sauna",
        value_fn=lambda st: _pick(st, "sauna_status"),
    ),
    HarviaSensorDescription(
        key="target_temperature",
        name="Target Temperature",
        native_unit_of_measurement="°C",
        icon="mdi:thermometer-check",
        value_fn=lambda st: _as_float(_pick(st, "target_temperature")),
    ),
    HarviaSensorDescription(
        key="humidity_setpoint",
        name="Target Humidity",
        native_unit_of_measurement="%",
        icon="mdi:water-percent",
        value_fn=lambda st: _as_float(_pick(st, "humidity_setpoint")),
    ),
    HarviaSensorDescription(
        key="heater_on_raw",
        name="Heater On",
        icon="mdi:radiator",
        value_fn=lambda st: _as_bool(_pick(st, "heater_on_raw")),
    ),
    HarviaSensorDescription(
        key="heater_state",
        name="Heater State",
        icon="mdi:radiator",
        value_fn=lambda st: _pick(st, "heater_state"),
    ),
    HarviaSensorDescription(
        key="screen_lock_on",
        name="Screen Lock",
        icon="mdi:lock",
        value_fn=lambda st: _as_bool(_pick(st, "screen_lock_on")),
    ),
    HarviaSensorDescription(
        key="steamer_on_raw",
        name="Steamer On",
        icon="mdi:cloud",
        value_fn=lambda st: _as_bool(_pick(st, "steamer_on_raw")),
    ),
    HarviaSensorDescription(
        key="steamer_state",
        name="Steamer State",
        icon="mdi:cloud",
        value_fn=lambda st: _pick(st, "steamer_state"),
    ),
    HarviaSensorDescription(
        key="light_on_raw",
        name="Light On",
        icon="mdi:lightbulb",
        value_fn=lambda st: _as_bool(_pick(st, "light_on_raw")),
    ),
    HarviaSensorDescription(
        key="active_profile",
        name="Active Profile",
        icon="mdi:playlist-check",
        value_fn=lambda st: _pick(st, "active_profile"),
    ),

    # --- Requested settings as individual sensors ---
    HarviaSensorDescription(
        key="remote_allowed",
        name="Remote allowed",
        icon="mdi:remote",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_bool(_pick(st, "remote_allowed")),
    ),
    HarviaSensorDescription(
        key="demo_mode",
        name="Demo mode",
        icon="mdi:flask",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_bool(_pick(st, "demo_mode")),
    ),
    HarviaSensorDescription(
        key="setting_max_on_time",
        name="Setting max on time",
        native_unit_of_measurement="min",  # minutes confirmed
        icon="mdi:timer-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_float(_pick(st, "setting_max_on_time")),
    ),
    HarviaSensorDescription(
        key="setting_max_temp",
        name="Setting max temp",
        native_unit_of_measurement="°C",
        icon="mdi:thermometer-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_float(_pick(st, "setting_max_temp")),
    ),
    HarviaSensorDescription(
        key="setting_temp_calibration",
        name="Setting temp calibration",
        native_unit_of_measurement="°C",
        icon="mdi:thermometer-lines",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_float(_pick(st, "setting_temp_calibration")),
    ),
    HarviaSensorDescription(
        key="setting_blackout_control",
        name="Setting blackout control",
        icon="mdi:power-plug-off",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_bool(_pick(st, "setting_blackout_control")),
    ),
    HarviaSensorDescription(
        key="setting_dehumidification",
        name="Setting dehumidification",
        icon="mdi:air-humidifier-off",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_bool(_pick(st, "setting_dehumidification")),
    ),
    HarviaSensorDescription(
        key="setting_remote_control",
        name="Setting remote control",
        icon="mdi:shield-home",
        entity_category=EntityCategory.DIAGNOSTIC,
        # this is a string like "door" in your normalized dict
        value_fn=lambda st: _pick(st, "setting_remote_control"),
    ),
    HarviaSensorDescription(
        key="setting_screen_saver_time",
        name="Setting screen saver time",
        native_unit_of_measurement="s",  # seconds confirmed
        icon="mdi:monitor-screenshot",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_float(_pick(st, "setting_screen_saver_time")),
    ),
    HarviaSensorDescription(
        key="setting_lock_settings",
        name="Setting lock settings",
        icon="mdi:lock-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_bool(_pick(st, "setting_lock_settings")),
    ),
    HarviaSensorDescription(
        key="setting_lock_additional",
        name="Setting lock additional",
        icon="mdi:lock-plus",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda st: _as_bool(_pick(st, "setting_lock_additional")),
    ),
)


# -------------------------
# Setup
# -------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HarviaDataUpdateCoordinator = data["coordinator"]
    devices = data["devices"]

    entities: list[SensorEntity] = []
    for dev in devices:
        for desc in SENSOR_DESCRIPTIONS:
            entities.append(HarviaCoordinatorSensor(coordinator, dev, desc))
        # Optional: keep a diagnostic "Settings" carrier for profiles/raw_state
        entities.append(HarviaSettingsDiagSensor(coordinator, dev))

    async_add_entities(entities)


# -------------------------
# Entities
# -------------------------

class HarviaBase(CoordinatorEntity):
    def __init__(self, coordinator: HarviaDataUpdateCoordinator, device: Any) -> None:
        super().__init__(coordinator)
        self._device = device
        self._serial = _serial(device)
        self._dev_id = str(getattr(device, "id", None) or getattr(device, "name", None) or "unknown")
        self._attr_device_info = _device_info(device)

    def _state(self) -> dict[str, Any]:
        # Prefer coordinator.data (authoritative), fallback to device.state
        data = self.coordinator.data or {}
        st = data.get(self._dev_id)
        if isinstance(st, dict) and st:
            return st
        st2 = getattr(self._device, "state", None)
        return st2 if isinstance(st2, dict) else {}

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class HarviaCoordinatorSensor(HarviaBase, SensorEntity):
    entity_description: HarviaSensorDescription

    def __init__(self, coordinator: HarviaDataUpdateCoordinator, device: Any, description: HarviaSensorDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{self._serial}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._state())


class HarviaSettingsDiagSensor(HarviaBase, SensorEntity):
    """Optional diagnostic sensor with profiles + raw_state (helps debugging without entity spam)."""

    def __init__(self, coordinator: HarviaDataUpdateCoordinator, device: Any) -> None:
        super().__init__(coordinator, device)
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{self._serial}_settings"
        self._attr_name = "Settings"
        self._attr_icon = "mdi:cog"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        return "ok" if self.available else "unavailable"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        st = self._state()
        return {
            "profiles": st.get("profiles"),
            # Uncomment if you want full raw state in attributes:
            # "raw_state": st,
        }
