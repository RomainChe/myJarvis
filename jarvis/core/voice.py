"""Socle voix : un tour de chat dont le texte vient d'une reconnaissance vocale (source `voix`, jamais `pwa:*`).

Plafond N0/N1 : la voix n'a ni appareil ni clé d'accès, donc aucune confirmation n'est possible.
N2 est refusé (« fais-la depuis l'application » : aucune demande n'est créée, cela viendra à l'étape 5), N3 aussi (`strong_auth` toujours faux). Le verrou `busy`,
le routeur et le journal sont ceux du chat : aucune voie vers `execute` hors de la garde de permissions.
"""
import hashlib

from jarvis.core.chat import ANSWER_MAX, REGISTRY, TEXT_MAX, Chat, ask, execute
from jarvis.core.levels import effective
from jarvis.core.llm import LLMUnavailable
from jarvis.core.permissions import Refused
from jarvis.core.tools import Level

SOURCE = "voix"
BUSY_MSG = "Je suis occupé, redemande dans un instant."
N2_MSG = "Action sensible : fais-la depuis l'application."
N3_MSG = "À faire sur le téléphone."


class Voice:
    def __init__(self, chat: Chat):
        self.chat = chat

    def handle(self, text: str) -> str:
        """Texte reconnu -> réponse à lire. Lève ValueError si le texte est vide ou trop long.

        L'appelant (STT/TTS) doit attraper toute exception (ex. échec du journal) et lire un message générique.
        """
        if not isinstance(text, str) or not 0 < len(text) <= TEXT_MAX:
            raise ValueError("texte invalide")
        chat = self.chat
        if not chat.busy.acquire(blocking=False):  # verrou partagé avec le chat
            return BUSY_MSG
        try:
            chat.audit.log(SOURCE, "chat", {"len": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()},
                           None, "auto", None)
            refused = [0]  # niveau le plus haut refusé dans ce tour

            def confirm(tool, args):  # pas d'appareil, pas de confirmation vocale (étape 7 du plan)
                refused[0] = max(refused[0], int(effective(tool)), int(tool.level))  # même règle que execute
                return False

            strong = lambda tool, args: False  # noqa: E731  (N3 jamais à la voix)
            try:
                routed = chat.router.route(text)
                if routed is None:
                    answer = ask(text, audit=chat.audit, confirm=confirm, strong_auth=strong, source=f"{SOURCE}/llm")
                else:
                    name, args = routed
                    result = execute(name, args, source=SOURCE, audit=chat.audit, confirm=confirm, strong_auth=strong)
                    answer = f"<{type(result).__name__}, {len(str(result))} car.>" if REGISTRY[name].private else str(result)
            except Refused:
                answer = "Action refusée."
            except LLMUnavailable as e:
                answer = str(e)
            except ValueError:  # message fixe : le texte d'origine peut venir du LLM (nom d'outil, arguments)
                answer = "Demande invalide."
            except Exception as e:  # pas de trace : elle pourrait contenir des arguments ou des noms de fichiers
                answer = f"Erreur interne : {type(e).__name__}"
            if refused[0] >= Level.N3:  # le message ne vient jamais du LLM
                answer = N3_MSG
            elif refused[0] >= Level.N2:
                answer = N2_MSG
            return answer[:ANSWER_MAX]
        finally:
            chat.busy.release()
