from __future__ import annotations

import inspect
from typing import Any

from homeassistant.helpers import device_registry as dr

from .constants import DOMAIN


def _attr_get(device: Any, key: str) -> str | None:
    for item in (getattr(device, "attr", None) or []):
        if isinstance(item, dict):
            if item.get("key") == key:
                v = item.get("value")
                return str(v) if v not in (None, "") else None
        else:
            if getattr(item, "key", None) == key:
                v = getattr(item, "value", None)
                return str(v) if v not in (None, "") else None
    return None


def build_device_info(device: Any) -> dict[str, Any]:
    serial = _attr_get(device, "serialNumber")
    hw = _attr_get(device, "HWID") or _attr_get(device, "powerUnitHWID")
    sw = _attr_get(device, "powerUnitFwVersion") or _attr_get(device, "initialFirmware")

    panel = _attr_get(device, "panelType")
    power_variant = _attr_get(device, "powerUnitVariant")

    # Modell sauber anreichern (HA-konform!)
    model = device.type
    details: list[str] = []
    if panel:
        details.append(f"Panel {panel}")
    if power_variant:
        details.append(f"PU {power_variant}")
    if details:
        model = f"{model} ({' / '.join(details)})"

    info: dict[str, Any] = {
        "identifiers": {(DOMAIN, device.id)},   # NICHT ändern
        "name": f"Harvia {device.type}",
        "manufacturer": "Harvia",
        "model": model,

        "serial_number": serial,
        "hw_version": hw,
        "sw_version": sw,
    }

    # None / "" entfernen
    info = {k: v for k, v in info.items() if v not in (None, "")}

    # nur von dieser HA-Version unterstützte Keys behalten
    allowed = set(inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters)
    allowed.discard("self")
    info = {k: v for k, v in info.items() if k in allowed}

    return info
