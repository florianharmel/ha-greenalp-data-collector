"""UI configuration and reauthentication."""

from datetime import datetime
from hashlib import sha256

import probatio

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector

from .client import AuthError, Client, GreenAlpError
from .const import CONF_INTERVAL, DEFAULT_INTERVAL, DOMAIN
from .cost import (
    CONF_TARIFFS, EFFECTIVE, PRICE, RETROACTIVE, SUBSCRIPTION,
    RetroactiveTariffError, update_tariffs,
)
from .normalization import PARIS

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
        options = self.config_entry.options
        errors = {}
        if user_input is not None:
            tariffs = options.get(CONF_TARIFFS, [])
            price = user_input.get(PRICE)
            effective = user_input.get(EFFECTIVE)
            if price is not None or effective or user_input.get(SUBSCRIPTION, 0):
                if price is None or not effective:
                    errors["base"] = "tariff_fields_required"
                else:
                    try:
                        tariffs = update_tariffs(
                            tariffs, effective, price, user_input.get(SUBSCRIPTION, 0),
                            datetime.now(PARIS).date(), user_input.get(RETROACTIVE, False),
                        )
                    except RetroactiveTariffError:
                        errors["base"] = "retroactive_tariff"
                    except ValueError:
                        errors["base"] = "invalid_tariff"
            if not errors:
                return self.async_create_entry(data={
                    **options, CONF_INTERVAL: user_input[CONF_INTERVAL], CONF_TARIFFS: tariffs,
                })
        schema = probatio.Schema({
            probatio.Required(CONF_INTERVAL, default=options.get(CONF_INTERVAL, DEFAULT_INTERVAL)):
                probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=168)),
            probatio.Optional(PRICE): selector.NumberSelector(selector.NumberSelectorConfig(
                min=0, step="any", mode=selector.NumberSelectorMode.BOX, unit_of_measurement="€/kWh",
            )),
            probatio.Optional(SUBSCRIPTION, default=0): selector.NumberSelector(selector.NumberSelectorConfig(
                min=0, step=0.01, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="€",
            )),
            probatio.Optional(EFFECTIVE): selector.DateSelector(),
            probatio.Optional(RETROACTIVE, default=False): selector.BooleanSelector(),
        })
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )
