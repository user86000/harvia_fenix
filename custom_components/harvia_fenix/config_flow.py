from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError

from .api import HarviaSaunaAPI, HarviaAuthError
from .constants import DOMAIN, CONF_ENDPOINTS_URL, DEFAULT_ENDPOINTS_URL

_LOGGER = logging.getLogger(__name__)


class HarviaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            endpoints_url = user_input.get(CONF_ENDPOINTS_URL, DEFAULT_ENDPOINTS_URL)

            api = HarviaSaunaAPI(self.hass, username=username, password=password, endpoints_url=endpoints_url)
            try:
                devices = await api.get_devices()
                if not devices:
                    errors["base"] = "no_devices"
            except HarviaAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Harvia config flow failed")
                errors["base"] = "unknown"
            finally:
                await api.close()

            if not errors:
                await self.async_set_unique_id(username)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Harvia Fenix",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_ENDPOINTS_URL: endpoints_url,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_ENDPOINTS_URL, default=DEFAULT_ENDPOINTS_URL): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None):
        entry_id = user_input.get("entry_id") if user_input else None
        if entry_id:
            self.context["entry_id"] = entry_id
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        entry_id = self.context.get("entry_id")
        if not entry_id:
            return self.async_abort(reason="unknown")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return self.async_abort(reason="unknown")

        username = entry.data.get(CONF_USERNAME)
        endpoints_url = entry.data.get(CONF_ENDPOINTS_URL, DEFAULT_ENDPOINTS_URL)

        if user_input is not None:
            new_password = user_input[CONF_PASSWORD]

            api = HarviaSaunaAPI(self.hass, username=username, password=new_password, endpoints_url=endpoints_url)
            try:
                devices = await api.get_devices()
                if not devices:
                    errors["base"] = "no_devices"
            except HarviaAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Harvia reauth failed")
                errors["base"] = "unknown"
            finally:
                await api.close()

            if not errors:
                new_data = dict(entry.data)
                new_data[CONF_PASSWORD] = new_password
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        schema = vol.Schema({vol.Required(CONF_PASSWORD): str})
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)


class CannotConnect(HomeAssistantError):
    def __init__(self, reason: str = "cannot_connect") -> None:
        self.reason = reason
        super().__init__(reason)




