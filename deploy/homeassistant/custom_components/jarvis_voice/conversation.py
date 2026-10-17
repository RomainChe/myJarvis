"""Entité d'agent de conversation : tout le texte reconnu passe par le Core (journal, plafond N0/N1), jamais par les intentions de HA."""
import logging

import aiohttp

from homeassistant.components.conversation import ConversationEntity, ConversationInput, ConversationResult
from homeassistant.helpers import intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_CLIENT, CONF_KEY, CONF_URL, FALLBACK_MSG, REPLY_MAX, TIMEOUT_S
from .core import build_request, parse_answer

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([JarvisConversation(entry)])


class JarvisConversation(ConversationEntity):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry):
        self._entry = entry
        self._attr_unique_id = entry.entry_id

    @property
    def supported_languages(self):
        return ["fr"]

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        data = self._entry.data
        try:
            url, headers, body = build_request(data[CONF_URL], data[CONF_KEY], data[CONF_CLIENT], user_input.text)
            async with async_get_clientsession(self.hass).post(
                    url, data=body, headers=headers, timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
                    allow_redirects=False) as resp:  # une redirection ne doit jamais emporter la clé ailleurs
                # lecture bornée : un Core détourné ne remplit pas la mémoire de HA
                answer = parse_answer(await resp.content.read(REPLY_MAX + 1), REPLY_MAX) if resp.status == 200 else None
        except (aiohttp.ClientError, TimeoutError, ValueError):
            answer = None
        if answer is None:  # 401/403/429, réseau : message fixe, rien de détaillé (ni texte, ni clé) dans le journal de HA
            _LOGGER.warning("Le Core n'a pas répondu à la phrase reçue")
            answer = FALLBACK_MSG
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(answer)  # réponse vide = Core « hors ligne » : rien n'est lu
        return ConversationResult(response=response, conversation_id=user_input.conversation_id)
