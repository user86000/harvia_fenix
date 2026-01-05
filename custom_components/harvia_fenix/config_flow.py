from __future__ import annotations

import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
)

from .api import HarviaFenixApi, HarviaAuthError, HarviaApiError
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
)

_LOGGER = logging.getLogger(__name__)

# Store selector values as strings (required by voluptuous schema in your HA build)
_INTERVAL_OPTIONS: list[SelectOptionDict] = [
    SelectOptionDict(value="30", label="30s"),
    SelectOptionDict(value="60", label="1min"),
    SelectOptionDict(value="120", label="2min"),
    SelectOptionDict(value="300", label="5min"),
    SelectOptionDict(value="600", label="10min"),
]

DEFAULT_DATA_INTERVAL_S = 30
DEFAULT_DEVICE_INTERVAL_S = 120

DEFAULT_DATA_INTERVAL_VALUE = str(DEFAULT_DATA_INTERVAL_S)      # "30"
DEFAULT_DEVICE_INTERVAL_VALUE = str(DEFAULT_DEVICE_INTERVAL_S)  # "120"

DATA_INTERVAL_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=_INTERVAL_OPTIONS,
        mode=SelectSelectorMode.DROPDOWN,
    )
)

DEVICE_INTERVAL_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=_INTERVAL_OPTIONS,
        mode=SelectSelectorMode.DROPDOWN,
    )
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_DATA_POLL_INTERVAL, default=DEFAULT_DATA_INTERVAL_VALUE): DATA_INTERVAL_SELECTOR,
        vol.Optional(CONF_DEVICE_POLL_INTERVAL, default=DEFAULT_DEVICE_INTERVAL_VALUE): DEVICE_INTERVAL_SELECTOR,
    }
)

STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


def _as_interval_seconds(value: Any, default_s: int) -> int:
    """Selector returns a string value; convert to int seconds safely."""
    try:
        return int(str(value))
    except Exception:
        return int(default_s)


class HarviaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            data_iv = _as_interval_seconds(
                user_input.get(CONF_DATA_POLL_INTERVAL, DEFAULT_DATA_INTERVAL_VALUE),
                DEFAULT_DATA_INTERVAL_S,
            )
            dev_iv = _as_interval_seconds(
                user_input.get(CONF_DEVICE_POLL_INTERVAL, DEFAULT_DEVICE_INTERVAL_VALUE),
                DEFAULT_DEVICE_INTERVAL_S,
            )

            session = async_get_clientsession(self.hass)
            api = HarviaFenixApi(
                session=session,
                endpoints_url=ENDPOINTS_URL,  # fixed
                username=username,
                password=password,
            )

            try:
                endpoints = await api.fetch_endpoints()
                tokens = await api.login(password=password)
            except HarviaAuthError:
                errors["base"] = "invalid_auth"
            except HarviaApiError as err:
                _LOGGER.debug("API error during setup: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error during setup: %s", err)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(username.lower())
                self._abort_if_unique_id_configured()

                data = {
                    CONF_USERNAME: username,
                    CONF_ENDPOINTS: endpoints,
                    CONF_ID_TOKEN: str(tokens.get("idToken")),
                    CONF_ACCESS_TOKEN: str(tokens.get("accessToken") or ""),
                    CONF_REFRESH_TOKEN: str(tokens.get("refreshToken")),
                    CONF_EXPIRES_IN: int(tokens.get("expiresIn") or 0),
                    CONF_TOKEN_OBTAINED_AT: int(time.time()),
                }
                options = {
                    CONF_DATA_POLL_INTERVAL: data_iv,
                    CONF_DEVICE_POLL_INTERVAL: dev_iv,
                }

                return self.async_create_entry(
                    title=f"Harvia Fenix ({username})",
                    data=data,
                    options=options,
                )

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None):
        self.reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm(user_input)

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        entry = getattr(self, "reauth_entry", None)
        if entry is None:
            return self.async_abort(reason="unknown")

        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm", data_schema=STEP_REAUTH_SCHEMA, errors=errors)

        password = user_input[CONF_PASSWORD]
        session = async_get_clientsession(self.hass)

        api = HarviaFenixApi(
            session=session,
            endpoints_url=ENDPOINTS_URL,  # fixed
            username=entry.data[CONF_USERNAME],
            password=password,
            id_token=entry.data.get(CONF_ID_TOKEN),
            access_token=entry.data.get(CONF_ACCESS_TOKEN),
            refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
            expires_in=entry.data.get(CONF_EXPIRES_IN),
            token_obtained_at=entry.data.get(CONF_TOKEN_OBTAINED_AT),
            endpoints=entry.data.get(CONF_ENDPOINTS, {}),
        )

        try:
            try:
                tokens = await api.refresh()
            except HarviaAuthError:
                tokens = await api.login(password=password)
        except HarviaAuthError:
            errors["base"] = "invalid_auth"
            return self.async_show_form(step_id="reauth_confirm", data_schema=STEP_REAUTH_SCHEMA, errors=errors)
        except Exception as err:
            _LOGGER.exception("Reauth failed: %s", err)
            errors["base"] = "unknown"
            return self.async_show_form(step_id="reauth_confirm", data_schema=STEP_REAUTH_SCHEMA, errors=errors)

        new_data = dict(entry.data)
        if tokens.get("idToken"):
            new_data[CONF_ID_TOKEN] = str(tokens["idToken"])
        if tokens.get("accessToken"):
            new_data[CONF_ACCESS_TOKEN] = str(tokens["accessToken"])
        if tokens.get("refreshToken"):
            new_data[CONF_REFRESH_TOKEN] = str(tokens["refreshToken"])
        if tokens.get("expiresIn") is not None:
            new_data[CONF_EXPIRES_IN] = int(tokens.get("expiresIn") or 0)

        new_data[CONF_TOKEN_OBTAINED_AT] = int(time.time())
        new_data[CONF_ENDPOINTS] = api.endpoints

        self.hass.config_entries.async_update_entry(entry, data=new_data)
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HarviaOptionsFlow(config_entry)


class HarviaOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            data_iv = _as_interval_seconds(
                user_input.get(CONF_DATA_POLL_INTERVAL, DEFAULT_DATA_INTERVAL_VALUE),
                DEFAULT_DATA_INTERVAL_S,
            )
            dev_iv = _as_interval_seconds(
                user_input.get(CONF_DEVICE_POLL_INTERVAL, DEFAULT_DEVICE_INTERVAL_VALUE),
                DEFAULT_DEVICE_INTERVAL_S,
            )
            return self.async_create_entry(
                title="",
                data={
                    CONF_DATA_POLL_INTERVAL: data_iv,
                    CONF_DEVICE_POLL_INTERVAL: dev_iv,
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DATA_POLL_INTERVAL,
                    default=str(self.entry.options.get(CONF_DATA_POLL_INTERVAL, DEFAULT_DATA_INTERVAL_S)),
                ): DATA_INTERVAL_SELECTOR,
                vol.Optional(
                    CONF_DEVICE_POLL_INTERVAL,
                    default=str(self.entry.options.get(CONF_DEVICE_POLL_INTERVAL, DEFAULT_DEVICE_INTERVAL_S)),
                ): DEVICE_INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


