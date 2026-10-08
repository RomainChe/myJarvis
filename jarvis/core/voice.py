"""Socle voix : un tour de chat dont le texte vient d'une reconnaissance vocale (source `voix`, jamais `pwa:*`).

Plafond N0/N1 : la voix n'a ni appareil ni clé d'accès, donc aucune confirmation n'est possible.
N2 est refusé (« fais-la depuis l'application » : aucune demande n'est créée), N3 aussi (`strong_auth` toujours faux). Le verrou `busy`,
le routeur et le journal sont ceux du chat : aucune voie vers `execute` hors de la garde de permissions.
"""
import hashlib
import threading

from jarvis.core.chat import ANSWER_MAX, REGISTRY, TEXT_MAX, Chat, ask, execute
from jarvis.core.levels import effective
from jarvis.core.llm import LLMUnavailable
from jarvis.core.permissions import Refused
from jarvis.core.tools import Level

SOURCE = "voix"
BUSY_MSG = "Je suis occupé, redemande dans un instant."
N2_MSG = "Action sensible : fais-la depuis l'application."
N3_MSG = "À faire sur le téléphone."
PRIVATE_MSG = "Fait, voir l'application."  # un outil privé a tourné : rien de son contenu (ni reformulé) n'est lu à voix haute


class _Tap:
    """Journal transmis à la garde : repère l'exécution d'un outil `private` (voies routeur et LLM passent par `log`)."""

    def __init__(self, audit):
        self._audit, self.private_ran = audit, False

    def log(self, source, tool, *a, **kw):
        t = REGISTRY.get(tool) if isinstance(tool, str) else None
        if t is not None and t.private and "en cours" in a[-1:]:  # écrit juste avant `tool.run`
            self.private_ran = True
        return self._audit.log(source, tool, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._audit, name)


class Voice:
    def __init__(self, chat: Chat, speaker=None):
        self.chat = chat
        self.speaker = speaker  # désactivé par défaut
        self.muted = False

    def say(self, answer: str) -> None:
        """Lit une réponse issue de `handle` (déjà bornée, résultats privés déjà masqués). Rien si muet ou sans voix."""
        if self.speaker is not None and not self.muted:
            self.speaker.say(answer)

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

            tap = _Tap(chat.audit)
            strong = lambda tool, args: False  # noqa: E731  (N3 jamais à la voix)
            try:
                routed = chat.router.route(text)
                if routed is None:
                    answer = ask(text, audit=tap, confirm=confirm, strong_auth=strong, source=f"{SOURCE}/llm")
                else:
                    name, args = routed
                    result = execute(name, args, source=SOURCE, audit=tap, confirm=confirm, strong_auth=strong)
                    answer = f"<{type(result).__name__}, {len(str(result))} car.>" if REGISTRY[name].private else str(result)
            except Refused:
                answer = "Action refusée."
            except LLMUnavailable as e:
                answer = str(e)
            except ValueError:  # message fixe : le texte d'origine peut venir du LLM (nom d'outil, arguments)
                answer = "Demande invalide."
            except Exception as e:  # pas de trace : elle pourrait contenir des arguments ou des noms de fichiers
                answer = f"Erreur interne : {type(e).__name__}"
            if tap.private_ran:
                answer = PRIVATE_MSG
            if refused[0] >= Level.N3:  # le message ne vient jamais du LLM
                answer = N3_MSG
            elif refused[0] >= Level.N2:
                answer = N2_MSG
            return answer[:ANSWER_MAX]
        finally:
            chat.busy.release()


class Listener:
    """Phrase captée (`Mic.on_utterance`) -> Whisper -> `Voice.handle` -> voix, dans un thread à part (la boucle du micro ne bloque pas).

    Une seule phrase en traitement : une autre qui arrive pendant ce temps est jetée (rien n'est mis en file). Aucune
    trace du texte reconnu ni de l'audio ; toute erreur donne un message générique. `on_text(texte, réponse)` est un
    affichage facultatif du terminal, jamais le journal.
    """

    def __init__(self, voice: Voice, stt, on_text=None):
        self.voice, self.stt, self.on_text = voice, stt, on_text
        self._busy = threading.Lock()
        self.error, self._thread = None, None

    def __call__(self, audio) -> bool:
        """False si la phrase est jetée (déjà occupé)."""
        if not self._busy.acquire(blocking=False):
            return False
        self._thread = threading.Thread(target=self._run, args=(audio,), daemon=True)
        self._thread.start()
        return True

    def _run(self, audio) -> None:
        try:
            text = self.stt.transcribe(audio)
            if text:  # rien d'intelligible : on ne répond pas
                answer = self.voice.handle(text)
                if self.on_text:
                    self.on_text(text, answer)
                self.voice.say(answer)
            self.error = None
        except Exception as e:  # ni audio ni texte : STTError a un message fixe, le reste un type seulement
            self.error = str(e) if type(e).__name__ == "STTError" else "Erreur vocale."
        finally:
            self._busy.release()
