from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HarviaFenixApi
from .coordinator import HarviaFenixCoordinator
from .const import (
    DOMAIN,
    ENDPOINTS_URL,
    CONF_USERNAME,
    CONF_ENDPOINTS,
    CONF_ID_TOKEN,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_EXPIRES_IN,
    CONF_TOKEN_OBTAINED_AT,
    CONF_DEVICE_POLL_INTERVAL,
    CONF_DATA_POLL_INTERVAL,
    DEFAULT_DEVICE_POLL_INTERVAL,
    DEFAULT_DATA_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_REVOKE_TOKENS = "revoke_tokens"
SERVICE_DUMP_RAW = "dump_raw"

FIELD_ENTRY_ID = "entry_id"
FIELD_DEVICE_ID = "device_id"
FIELD_MAX_CHARS = "max_chars"
FIELD_INCLUDE_LATEST = "include_latest"
FIELD_INCLUDE_STATE = "include_state"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)

    async def _persist_tokens(payload: dict[str, Any]) -> None:
        cfg_entry = hass.config_entries.async_get_entry(entry.entry_id)
        if cfg_entry is None:
            return

        new_data: dict[str, Any] = dict(cfg_entry.data)

        # tokens
        if payload.get("idToken") is None:
            new_data.pop(CONF_ID_TOKEN, None)
        else:
            new_data[CONF_ID_TOKEN] = str(payload.get("idToken"))

        if payload.get("accessToken") is None:
            new_data.pop(CONF_ACCESS_TOKEN, None)
        else:
            new_data[CONF_ACCESS_TOKEN] = str(payload.get("accessToken") or "")

        if payload.get("refreshToken") is None:
            new_data.pop(CONF_REFRESH_TOKEN, None)
        else:
            new_data[CONF_REFRESH_TOKEN] = str(payload.get("refreshToken"))

        expires_in = payload.get("expiresIn")
        if expires_in is None:
            new_data.pop(CONF_EXPIRES_IN, None)
        else:
            try:
                new_data[CONF_EXPIRES_IN] = int(expires_in or 0)
            except (TypeError, ValueError):
                new_data.pop(CONF_EXPIRES_IN, None)

        obtained_at = payload.get("tokenObtainedAt")
        if obtained_at is None:
            new_data.pop(CONF_TOKEN_OBTAINED_AT, None)
        else:
            try:
                new_data[CONF_TOKEN_OBTAINED_AT] = int(obtained_at)
            except (TypeError, ValueError):
                new_data.pop(CONF_TOKEN_OBTAINED_AT, None)

        hass.config_entries.async_update_entry(cfg_entry, data=new_data)

    api = HarviaFenixApi(
        session=session,
        endpoints_url=ENDPOINTS_URL,  # fixed
        username=entry.data[CONF_USERNAME],
        password=None,  # not stored
        id_token=entry.data.get(CONF_ID_TOKEN),
        access_token=entry.data.get(CONF_ACCESS_TOKEN),
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        expires_in=entry.data.get(CONF_EXPIRES_IN),
        token_obtained_at=entry.data.get(CONF_TOKEN_OBTAINED_AT),
        endpoints=entry.data.get(CONF_ENDPOINTS, {}),
        token_update_callback=_persist_tokens,
    )

    dev_iv = int(entry.options.get(CONF_DEVICE_POLL_INTERVAL, DEFAULT_DEVICE_POLL_INTERVAL))
    data_iv = int(entry.options.get(CONF_DATA_POLL_INTERVAL, DEFAULT_DATA_POLL_INTERVAL))

    coordinator = HarviaFenixCoordinator(hass, api, dev_iv, data_iv)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    _ensure_services_registered(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _ensure_services_registered(hass: HomeAssistant) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    if store.get("_services_registered"):
        return

    async def _handle_revoke_tokens(call: ServiceCall) -> None:
        entry_id: str | None = call.data.get(FIELD_ENTRY_ID)

        if entry_id:
            entry_ids = [entry_id]
        else:
            entry_ids = [
                k for k in hass.data.get(DOMAIN, {}).keys()
                if isinstance(k, str) and k and k != "_services_registered"
            ]

        for eid in entry_ids:
            coordinator: HarviaFenixCoordinator | None = hass.data.get(DOMAIN, {}).get(eid)
            if coordinator is None:
                continue
            try:
                await coordinator.api.revoke()
            except Exception as err:
                _LOGGER.warning("%s: revoke call failed for %s: %s", DOMAIN, eid, err)
            await hass.config_entries.async_reload(eid)

    async def _handle_dump_raw(call: ServiceCall) -> None:
        entry_id: str | None = call.data.get(FIELD_ENTRY_ID)
        only_device_id: str | None = call.data.get(FIELD_DEVICE_ID)

        max_chars = int(call.data.get(FIELD_MAX_CHARS, 4000))
        include_latest = bool(call.data.get(FIELD_INCLUDE_LATEST, True))
        include_state = bool(call.data.get(FIELD_INCLUDE_STATE, True))

        if entry_id:
            entry_ids = [entry_id]
        else:
            entry_ids = [
                k for k in hass.data.get(DOMAIN, {}).keys()
                if isinstance(k, str) and k and k != "_services_registered"
            ]

        if not entry_ids:
            _LOGGER.warning("%s.dump_raw: no entries found", DOMAIN)
            return

        for eid in entry_ids:
            coordinator: HarviaFenixCoordinator | None = hass.data.get(DOMAIN, {}).get(eid)
            if coordinator is None:
                _LOGGER.warning("%s.dump_raw: entry_id %s not loaded", DOMAIN, eid)
                continue

            api = coordinator.api
            api.set_request_debug(True, max_chars=max_chars)

            try:
                _LOGGER.warning("========== %s.dump_raw entry=%s ==========", DOMAIN, eid)

                devices = await api.get_devices()
                devices_payload = []
                for d in devices:
                    devices_payload.append(
                        {
                            "id": d.id,
                            "type": d.type,
                            "attrs": d.attrs or {},
                        }
                    )
                _log_json_truncated(
                    prefix=f"{DOMAIN}.dump_raw devices (entry={eid})",
                    obj=devices_payload,
                    max_chars=max_chars,
                )

                device_ids = [only_device_id] if only_device_id else [d.id for d in devices]

                for did in device_ids:
                    if include_state:
                        try:
                            state = await api.get_device_state(did)
                            _log_json_truncated(
                                prefix=f"{DOMAIN}.dump_raw state device={did} (entry={eid})",
                                obj=state,
                                max_chars=max_chars,
                            )
                        except Exception as err:
                            _LOGGER.warning("%s.dump_raw: state failed device=%s entry=%s: %s", DOMAIN, did, eid, err)

                    if include_latest:
                        try:
                            latest = await api.get_latest_data(did)
                            _log_json_truncated(
                                prefix=f"{DOMAIN}.dump_raw latest-data device={did} (entry={eid})",
                                obj=latest,
                                max_chars=max_chars,
                            )
                        except Exception as err:
                            _LOGGER.warning("%s.dump_raw: latest-data failed device=%s entry=%s: %s", DOMAIN, did, eid, err)

                _LOGGER.warning("========== %s.dump_raw done entry=%s ==========", DOMAIN, eid)

            finally:
                api.set_request_debug(False)

    hass.services.async_register(DOMAIN, SERVICE_REVOKE_TOKENS, _handle_revoke_tokens)
    hass.services.async_register(DOMAIN, SERVICE_DUMP_RAW, _handle_dump_raw)
    store["_services_registered"] = True


def _log_json_truncated(prefix: str, obj: Any, max_chars: int) -> None:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        s = str(obj)

    if max_chars and len(s) > max_chars:
        s = s[:max_chars] + "\n…(truncated)…"

    _LOGGER.warning("%s:\n%s", prefix, s)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN].pop(entry.entry_id)
    return True

