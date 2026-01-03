from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD

from .api import HarviaSaunaAPI
from .constants import DOMAIN


class HarviaSaunaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        errors = {}

        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            api = HarviaSaunaAPI(user_input[CONF_USERNAME], user_input[CONF_PASSWORD], self.hass)
            await api.async_init()
            ok = await api.authenticate()
            if ok:
                return self.async_create_entry(title="Harvia Sauna", data=user_input)
            errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

