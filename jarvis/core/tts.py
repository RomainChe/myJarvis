"""Synthèse vocale Piper, sortie seule (Phase 4 étape 3) + anti-écho.

Voix chargée seulement si ses fichiers correspondent au SHA-256 de models/MANIFEST.json (condition 23). Synthèse en
mémoire, phrase par phrase (on parle avant la fin) ; jamais de fichier audio ni de cache (14, 21). Le journal ne reçoit
que la longueur du texte. Toute erreur audio/Piper donne un message générique, jamais le texte lu (20).
Anti-écho (8) : le futur module micro ne doit rien écouter tant que `is_speaking()` ou avant `ignore_until()`.
"""
import json
import os
import threading
import time
from pathlib import Path

from jarvis.core.chat import ANSWER_MAX
from jarvis.core.modelcheck import is_good

ROOT = Path(__file__).resolve().parent.parent.parent
VOICE = "piper/fr_FR-tom-medium.onnx"
LENGTH_SCALE = 1.05
MARGIN_S = 0.4
SOURCE = "voix"
ERR_MSG = "Synthèse vocale indisponible."


class TTSError(Exception):
    """Message fixe : ne contient jamais le texte lu."""


def audio_device(var="JARVIS_AUDIO_OUT"):
    """Variable d'environnement (nom ou index) ; vide = périphérique par défaut. Jamais de nom dans le dépôt (31)."""
    raw = os.environ.get(var, "").strip()
    return int(raw) if raw.isascii() and raw.isdigit() else (raw or None)


class Speaker:
    """Lecteur bas niveau. `say` est INTERNE : seul `Voice.say` doit l'appeler (muet, réponses déjà masquées)."""

    def __init__(self, audit=None, *, models=ROOT / "models", margin=MARGIN_S, sd=None, loader=None,
                 manifest=ROOT / "models" / "MANIFEST.json"):
        self.audit, self.models, self.margin, self.manifest = audit, Path(models), margin, Path(manifest)
        self._lock = threading.Lock()  # test is_speaking + set de say() atomique
        self._sd, self._loader, self._voice = sd, loader, None
        self._speaking = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.error = None
        self._end = 0.0  # time.monotonic() de la fin de la dernière lecture

    def _load(self):
        if self._voice:
            return
        os.environ["HF_HUB_OFFLINE"] = "1"  # imposé, pas suggéré : aucun accès réseau depuis la synthèse
        entries = {e["path"]: e for e in json.loads(self.manifest.read_text(encoding="utf-8"))["files"]}
        for path in (VOICE, VOICE + ".json"):  # la voix ET sa config doivent figurer au manifeste et être vérifiées
            e = entries.get(path)
            if e is None or not is_good(self.models / path, e["size"], e["sha256"]):
                raise TTSError("voix non vérifiée")
        if self._loader is None:
            from piper import PiperVoice
            self._loader = PiperVoice.load
        self._voice = self._loader(str(self.models / VOICE))

    def _play(self, text):
        from piper import SynthesisConfig
        sd = self._sd or __import__("sounddevice")
        cfg = SynthesisConfig(length_scale=LENGTH_SCALE)
        stream = None
        try:
            for chunk in self._voice.synthesize(text, cfg):  # un morceau par phrase
                if self._stop.is_set():
                    break
                if stream is None:
                    stream = sd.RawOutputStream(samplerate=chunk.sample_rate, channels=1, dtype="int16",
                                                device=audio_device())
                    stream.start()
                stream.write(chunk.audio_int16_bytes)
            return "interrompu" if self._stop.is_set() else "ok"
        finally:
            if stream is not None:
                stream.abort() if self._stop.is_set() else stream.stop()
                stream.close()

    def _run(self, text):
        result = "ok"
        try:
            self._load()
            result = self._play(text)
        except Exception:  # pas de trace ni de texte : un message fixe
            result = "erreur"
        finally:
            self._end = time.monotonic()
            self.error = ERR_MSG if result == "erreur" else None  # avant l'audit : visible même si le journal échoue
            self._speaking.clear()
            try:
                if self.audit:
                    self.audit.log(SOURCE, "tts", {"len": len(text)}, None, "auto", result)
            except Exception:  # le thread ne doit pas mourir ; message générique, sans texte
                self.error = self.error or ERR_MSG

    def say(self, text: str, block: bool = True) -> None:
        """Lit `text` (tronqué à ANSWER_MAX). Erreur -> self.error (message générique), jamais d'exception."""
        text = text[:ANSWER_MAX]
        if not text.strip():
            return
        with self._lock:
            if self._speaking.is_set():
                return
            self.error = None
            self._stop.clear()
            self._speaking.set()
        self._thread = threading.Thread(target=self._run, args=(text,), daemon=True)
        self._thread.start()
        if block:
            self._thread.join()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def ignore_until(self) -> float:
        """Échéance (time.monotonic) avant laquelle le micro doit ignorer l'audio : infinie pendant la lecture."""
        return float("inf") if self.is_speaking() else self._end + self.margin
