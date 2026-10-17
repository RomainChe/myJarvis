"""Client voix du PC : `python -m jarvis voice`.

Micro (openWakeWord), Whisper (GPU) et Piper restent sur le PC ; seul le texte reconnu part vers le Core du mini-PC
(`POST /api/voice`, HTTPS Tailscale). La clé d'appareil est dans le coffre Windows (`python -m jarvis secret set voice_key`,
valeur donnée par `python -m jarvis device add` sur le Core), jamais dans un fichier. Plafond N0/N1 imposé par le Core.
Un second micro = un autre processus avec un autre `JARVIS_VOICE_CLIENT` (le Core journalise `appareil/client`).
"""
import json
import os
import re
import sys
import time
import urllib.request

import keyring.errors

from jarvis.core.host import trusted_base_url
from jarvis.core.secrets import get_secret
from jarvis.core.voice import Voice

URL_ENV, CLIENT_ENV = "JARVIS_CORE_URL", "JARVIS_VOICE_CLIENT"
TIMEOUT_S = 60  # un tour LLM local peut durer
REPLY_MAX = 16384
UNREACHABLE_MSG = "Le Core ne répond pas."
_CLIENT = re.compile(r"[a-z0-9_-]{1,32}")


def core_url() -> str:
    """https://nom.ts.net[:port] ; la clé ne part jamais en clair (pas de http, même sur Tailscale)."""
    url = trusted_base_url(os.environ.get(URL_ENV, "").strip().rstrip("/"), URL_ENV)
    if not url.startswith("https://"):
        raise ValueError(f"{URL_ENV} : https requis")
    return url


def client_id() -> str:
    value = os.environ.get(CLIENT_ENV, "pc").strip()
    if not _CLIENT.fullmatch(value):
        raise ValueError(f"{CLIENT_ENV} : 1 à 32 caractères parmi a-z 0-9 _ -")
    return value


class RemoteVoice(Voice):
    """Comme `Voice` (muet, lecture), mais `handle` interroge le Core : rien ne s'exécute sur le PC."""

    def __init__(self, url: str, key: str, client: str, speaker=None, urlopen=urllib.request.urlopen):
        super().__init__(None, speaker)
        self._url, self._key, self._client, self._open = url, key, client, urlopen

    def handle(self, text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("texte invalide")
        body = json.dumps({"text": text, "client": self._client}).encode()
        req = urllib.request.Request(self._url + "/api/voice", body, {
            "Content-Type": "application/json", "Authorization": f"Bearer {self._key}", "Origin": self._url})
        try:
            with self._open(req, timeout=TIMEOUT_S) as r:
                answer = json.loads(r.read(REPLY_MAX + 1))["answer"]
        except (OSError, ValueError, KeyError, TypeError):  # réseau, 401/429, réponse illisible : message fixe, rien de détaillé
            return UNREACHABLE_MSG
        return answer if isinstance(answer, str) and len(answer) <= REPLY_MAX else UNREACHABLE_MSG


def _timed(timings: dict, key: str, fn, arg):
    start = time.monotonic()
    try:
        return fn(arg)
    finally:
        timings[key] = time.monotonic() - start


def run(audit) -> int:
    try:
        url, client = core_url(), client_id()
    except ValueError as e:
        print(e)
        return 2
    try:
        key = get_secret("voice_key")
    except keyring.errors.KeyringError:
        key = None
    if not key:
        print("clé absente : python -m jarvis secret set voice_key")
        return 2
    from jarvis.core.mic import Mic, threshold_from_env, wake_name_from_env
    from jarvis.core.stt import Transcriber
    from jarvis.core.tts import Speaker
    from jarvis.core.voice import Listener
    voice = RemoteVoice(url, key, client, Speaker(audit))
    stt, timings = Transcriber(), {}
    _transcribe, _handle = stt.transcribe, voice.handle
    stt.transcribe = lambda audio: _timed(timings, "stt", _transcribe, audio)
    voice.handle = lambda text: _timed(timings, "core", _handle, text)
    show = lambda text, answer: print(f"> {text}\n{answer}\n[stt {timings['stt']:.1f} s, core {timings['core']:.1f} s]") if sys.stdout.isatty() else None
    listener = Listener(voice, stt, show)
    mic = Mic(listener, audit, voice.speaker, on_state=lambda s: print(f"[{s}]"), threshold=threshold_from_env(), wake_name=wake_name_from_env())
    print(f"Client voix « {client} » vers {url}. Dis le mot d'appel puis une phrase. Ctrl+C pour quitter.")
    try:
        mic.run()
    except KeyboardInterrupt:
        pass
    for err in (mic.error, listener.error, voice.speaker.error):
        if err:
            print(err)
    return 1 if mic.error else 0
