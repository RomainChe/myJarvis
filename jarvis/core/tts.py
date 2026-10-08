"""Synthèse vocale Piper, sortie seule (Phase 4 étape 3) + anti-écho.

Voix chargée seulement si ses fichiers correspondent au SHA-256 de models/MANIFEST.json (condition 23). Synthèse en
mémoire, phrase par phrase (on parle avant la fin) ; jamais de fichier audio ni de cache (14, 21). Le journal ne reçoit
que la longueur du texte. Toute erreur audio/Piper donne un message générique, jamais le texte lu (20).
Anti-écho (8) : le futur module micro ne doit rien écouter tant que `is_speaking()` ou avant `ignore_until()`.
"""
import importlib.util
import json
import os
import threading
import time
from pathlib import Path

from jarvis.core.chat import ANSWER_MAX

ROOT = Path(__file__).resolve().parent.parent.parent
VOICE = "piper/fr_FR-tom-medium.onnx"
LENGTH_SCALE = 1.05
MARGIN_S = 0.4
SOURCE = "voix"
ERR_MSG = "Synthèse vocale indisponible."


class TTSError(Exception):
    """Message fixe : ne contient jamais le texte lu."""


def _fetch_models():  # scripts/ n'est pas un paquet installé : chargement par chemin
    spec = importlib.util.spec_from_file_location("fetch_models", ROOT / "scripts" / "fetch_models.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def audio_device():
    """JARVIS_AUDIO_OUT : nom ou index ; vide = sortie par défaut."""
    raw = os.environ.get("JARVIS_AUDIO_OUT", "").strip()
    return int(raw) if raw.isdigit() else (raw or None)


class Speaker:
    def __init__(self, audit=None, *, models=ROOT / "models", margin=MARGIN_S, sd=None, loader=None):
        self.audit, self.models, self.margin = audit, Path(models), margin
        self._sd, self._loader, self._voice = sd, loader, None
        self._speaking = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.error = None
        self._end = 0.0  # time.monotonic() de la fin de la dernière lecture

    def _load(self):
        if self._voice:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        fm = _fetch_models()
        for e in json.loads((ROOT / "models" / "MANIFEST.json").read_text(encoding="utf-8"))["files"]:
            if e["path"].startswith("piper/") and not fm.is_good(self.models / e["path"], e["size"], e["sha256"]):
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
            self._speaking.clear()
            if self.audit:
                self.audit.log(SOURCE, "tts", {"len": len(text)}, None, "auto", result)
        self.error = ERR_MSG if result == "erreur" else None

    def say(self, text: str, block: bool = True) -> None:
        """Lit `text` (tronqué à ANSWER_MAX). Erreur -> self.error (message générique), jamais d'exception."""
        text = text[:ANSWER_MAX]
        if not text.strip() or self._speaking.is_set():
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
