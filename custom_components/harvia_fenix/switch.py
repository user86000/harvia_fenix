from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .constants import DOMAIN, DEVICE_COORDINATOR, DATA_COORDINATOR
from .coordinator import HarviaDeviceCoordinator, HarviaDataCoordinator
from .api import HarviaDevice
from .device_info import build_device_info

import logging
_LOGGER = logging.getLogger(__name__)


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
    device_coordinator: HarviaDeviceCoordinator = hass.data[DOMAIN][entry.entry_id][DEVICE_COORDINATOR]
    devices: list[HarviaDevice] = (device_coordinator.data or {}).get("devices", [])

    entities: list[SwitchEntity] = []
    for dev in devices:
        for spec in SWITCH_SPECS:
            entities.append(HarviaSaunaSwitch(hass, entry.entry_id, device_coordinator, dev, spec))

    async_add_entities(entities)


class HarviaSaunaSwitch(CoordinatorEntity[HarviaDeviceCoordinator], SwitchEntity):
    """Sauna power switch. Status follows states[device_id]['sauna_status'] (device coordinator)."""

    _attr_icon = "mdi:sauna"

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        coordinator: HarviaDeviceCoordinator,
        device: HarviaDevice,
        spec: HarviaSwitchSpec,
    ) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._entry_id = entry_id
        self._device = device
        self._spec = spec

        self._attr_unique_id = f"{device.id}_switch_{spec.command.lower()}"
        self._attr_name = f"Harvia {device.type} {spec.name}"
        self._attr_device_info = build_device_info(device)

    @property
    def _data_coordinator(self) -> HarviaDataCoordinator:
        return self._hass.data[DOMAIN][self._entry_id][DATA_COORDINATOR]

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.data.get("states", {}).get(self._device.id)
        if not isinstance(state, dict):
            return None

        val = state.get("sauna_status")

        # Explizite Harvia-Logik:
        # 1 = ON
        # 0 = OFF
        try:
            iv = int(val)
        except (TypeError, ValueError):
            return None

        if iv == 1:
            return True
        if iv in (0, 2, 3):
            return False

        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        payload = {"state": on, "cabin_id": "C1"}

        try:
            resp = await self.coordinator.api.async_send_device_command(
                device_id=self._device.id,
                command=self._spec.command,
                payload=payload,
            )
        except Exception:
            _LOGGER.exception(
                "Harvia SWITCH RESP ERROR device=%s command=%s",
                self._device.id,
                self._spec.command,
            )
            raise

        # Backend/Cloud + Polling: mehrere Refreshes helfen, dass der UI-Status schneller nachzieht
        await self.coordinator.async_request_refresh()
        await self._data_coordinator.async_request_refresh()
        await asyncio.sleep(3)
        await self.coordinator.async_request_refresh()
        await self._data_coordinator.async_request_refresh()
        await asyncio.sleep(6)
        await self.coordinator.async_request_refresh()
        await self._data_coordinator.async_request_refresh()

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
