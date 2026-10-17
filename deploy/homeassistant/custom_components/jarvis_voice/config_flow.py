"""Configuration par l'interface : URL du Core, clé de l'appareil de portée voix (`device add --voice`), nom du micro."""
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import CONF_CLIENT, CONF_KEY, CONF_URL, DEFAULT_CLIENT, DEFAULT_URL, DOMAIN
from .core import build_request


class JarvisVoiceFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                build_request(user_input[CONF_URL], user_input[CONF_KEY], user_input[CONF_CLIENT], "x")
            except ValueError:
                errors["base"] = "invalid"
            else:
                await self.async_set_unique_id(user_input[CONF_CLIENT])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"JARVIS ({user_input[CONF_CLIENT]})", data=user_input)
        schema = vol.Schema({
            vol.Required(CONF_URL, default=DEFAULT_URL): str,
            vol.Required(CONF_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            vol.Required(CONF_CLIENT, default=DEFAULT_CLIENT): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
