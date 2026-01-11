from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .constants import DOMAIN, DATA_COORDINATOR
from .coordinator import HarviaCoordinator
from .api import HarviaDevice
from .device_info import build_device_info


def _get_latest_payload(coordinator: HarviaCoordinator, device_id: str) -> dict[str, Any] | None:
    latest_map = coordinator.data.get("latest_data", {})
    payload = latest_map.get(device_id)
    return payload if isinstance(payload, dict) else None


def _get_latest_data_dict(coordinator: HarviaCoordinator, device_id: str) -> dict[str, Any] | None:
    payload = _get_latest_payload(coordinator, device_id)
    if not isinstance(payload, dict):
        return None
    d = payload.get("data")
    return d if isinstance(d, dict) else None


def _coerce_bool(val: Any) -> Optional[bool]:
    """Coerce common bool-ish values."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(int(val))
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("1", "true", "on", "running", "active", "heating", "started", "start"):
            return True
        if s in ("0", "false", "off", "inactive", "stopped", "stop", "standby", "idle", "ready"):
            return False
    return None


@dataclass(frozen=True)
class HarviaSwitchSpec:
    command: str
    name: str


SWITCH_SPECS: list[HarviaSwitchSpec] = [
    HarviaSwitchSpec(command="SAUNA", name="Sauna"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HarviaCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    devices: list[HarviaDevice] = coordinator.data.get("devices", [])

    entities: list[SwitchEntity] = []
    for dev in devices:
        for spec in SWITCH_SPECS:
            entities.append(HarviaSaunaSwitch(coordinator, dev, spec))

    async_add_entities(entities)


class HarviaSaunaSwitch(CoordinatorEntity[HarviaCoordinator], SwitchEntity):
    """Sauna power switch. Status follows states[device_id]['sauna_status']."""

    _attr_icon = "mdi:sauna"

    def __init__(self, coordinator: HarviaCoordinator, device: HarviaDevice, spec: HarviaSwitchSpec) -> None:
        super().__init__(coordinator)
        self._device = device
        self._spec = spec

        self._attr_unique_id = f"{device.id}_switch_{spec.command.lower()}"
        self._attr_name = f"Harvia {device.type} {spec.name}"
        self._attr_device_info = build_device_info(device)

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.data.get("states", {}).get(self._device.id)
        if not isinstance(state, dict):
            return None

        val = state.get("sauna_status")

        # 1/0, True/False, "on/off" abfangen
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(int(val))
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("1", "true", "on", "running", "active", "heating", "started"):
                return True
            if s in ("0", "false", "off", "inactive", "stopped", "standby", "idle", "ready"):
                return False

        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        # API Doku: command={"type":"SAUNA","state":"on/off"}
        await self.coordinator.api.async_send_device_command(
            device_id=self._device.id,
            command=self._spec.command,
            payload={"state": on},
        )

        # Cloud + dein Polling: 30s ist realistisch -> wir holen in kurzen Abständen nach,
        # damit die UI schneller "mitzieht".
        await self.coordinator.async_request_refresh()
        await asyncio.sleep(3)
        await self.coordinator.async_request_refresh()
        await asyncio.sleep(6)
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        # Debug: zeig beide Quellen, damit du siehst, wer hinterherhinkt
        state = self.coordinator.data.get("states", {}).get(self._device.id, {})
        data = _get_latest_data_dict(self.coordinator, self._device.id) or {}

        attrs: dict[str, Any] = {
            "states_sauna_status": state.get("sauna_status") if isinstance(state, dict) else None,
            "latest_onOffTrigger": data.get("onOffTrigger") if isinstance(data, dict) else None,
            "latest_heatOn": data.get("heatOn") if isinstance(data, dict) else None,
            "latest_steamOn": data.get("steamOn") if isinstance(data, dict) else None,
        }

        payload = _get_latest_payload(self.coordinator, self._device.id)
        if isinstance(payload, dict):
            attrs.update(
                {
                    "timestamp": payload.get("timestamp"),
                    "shadowName": payload.get("shadowName"),
                    "subId": payload.get("subId"),
                    "type": payload.get("type"),
                }
            )

        return attrs
