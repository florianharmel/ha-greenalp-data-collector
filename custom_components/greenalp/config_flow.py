"""UI configuration and reauthentication."""

from hashlib import sha256

import probatio

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector

from .client import AuthError, Client, GreenAlpError
from .const import CONF_INTERVAL, DEFAULT_INTERVAL, DOMAIN

PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


class GreenAlpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, username, password):
        try:
            await self.hass.async_add_executor_job(Client(username, password).login)
        except AuthError:
            return {"base": "invalid_auth"}
        except GreenAlpError:
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(sha256(username.casefold().encode()).hexdigest())
            self._abort_if_unique_id_configured()
            errors = await self._validate(username, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(
                    title="GreenAlp",
                    data={CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema({
                probatio.Required(CONF_USERNAME): selector.TextSelector(),
                probatio.Required(CONF_PASSWORD): PASSWORD,
            }),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            errors = await self._validate(entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema({probatio.Required(CONF_PASSWORD): PASSWORD}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return GreenAlpOptionsFlow()


class GreenAlpOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema({
                probatio.Required(
                    CONF_INTERVAL, default=self.config_entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL)
                ): probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=168)),
            }),
        )
