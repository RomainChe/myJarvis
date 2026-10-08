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

import numpy as np

from jarvis.core.chat import ANSWER_MAX
from jarvis.core.modelcheck import is_good

ROOT = Path(__file__).resolve().parent.parent.parent
# JARVIS_VOICE choisit la voix (nom -> fichier, locuteur) ; jamais un chemin libre.
VOICES = {"tom": ("piper/fr_FR-tom-medium.onnx", None), "gilles": ("piper/fr_FR-gilles-low.onnx", None),
          "pierre": ("piper/fr_FR-upmc-medium.onnx", 1)}
DEFAULT_VOICE = "tom"
LENGTH_SCALE, RATE_MIN, RATE_MAX = 1.05, 0.8, 1.6  # JARVIS_VOICE_RATE : > 1 = plus lent
FX_DELAY_S, FX_MIX = 0.007, 0.6  # effet « IA » (JARVIS_VOICE_FX=0 le coupe) : écho court qui donne le timbre métallique
MARGIN_S = 0.4
SOURCE = "voix"
ERR_MSG = "Synthèse vocale indisponible."


class TTSError(Exception):
    """Message fixe : ne contient jamais le texte lu."""


def audio_device(var="JARVIS_AUDIO_OUT"):
    """Variable d'environnement (nom ou index) ; vide = périphérique par défaut. Jamais de nom dans le dépôt (31)."""
    raw = os.environ.get(var, "").strip()
    return int(raw) if raw.isascii() and raw.isdigit() else (raw or None)


def rate_from_env():
    try:
        r = float(os.environ.get("JARVIS_VOICE_RATE", LENGTH_SCALE))
    except ValueError:
        return LENGTH_SCALE
    return min(max(r, RATE_MIN), RATE_MAX) if r == r else LENGTH_SCALE  # r != r : NaN


def robot(pcm: bytes, rate: int) -> bytes:
    """Ajoute au son un écho de 7 ms (filtre en peigne) : timbre métallique, volume inchangé."""
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    d = int(rate * FX_DELAY_S)
    y = x.copy()
    y[d:] += FX_MIX * x[:-d]
    return (y / (1 + FX_MIX)).astype(np.int16).tobytes()


class Speaker:
    """Lecteur bas niveau. `say` est INTERNE : seul `Voice.say` doit l'appeler (muet, réponses déjà masquées)."""

    def __init__(self, audit=None, *, models=ROOT / "models", margin=MARGIN_S, sd=None, loader=None,
                 manifest=ROOT / "models" / "MANIFEST.json", voice=None, rate=None, fx=None):
        self.audit, self.models, self.margin, self.manifest = audit, Path(models), margin, Path(manifest)
        self.voice_name = voice or os.environ.get("JARVIS_VOICE", "").strip().lower() or DEFAULT_VOICE
        self.rate = rate_from_env() if rate is None else rate
        self.fx = os.environ.get("JARVIS_VOICE_FX", "1").strip() != "0" if fx is None else fx
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
        if self.voice_name not in VOICES:
            raise TTSError("voix inconnue")
        voice = VOICES[self.voice_name][0]
        entries = {e["path"]: e for e in json.loads(self.manifest.read_text(encoding="utf-8"))["files"]}
        for path in (voice, voice + ".json"):  # la voix ET sa config doivent figurer au manifeste et être vérifiées
            e = entries.get(path)
            if e is None or not is_good(self.models / path, e["size"], e["sha256"]):
                raise TTSError("voix non vérifiée")
        if self._loader is None:
            from piper import PiperVoice
            self._loader = PiperVoice.load
        self._voice = self._loader(str(self.models / voice))

    def _play(self, text):
        from piper import SynthesisConfig
        sd = self._sd or __import__("sounddevice")
        cfg = SynthesisConfig(length_scale=self.rate, speaker_id=VOICES[self.voice_name][1])
        stream = None
        try:
            for chunk in self._voice.synthesize(text, cfg):  # un morceau par phrase
                if self._stop.is_set():
                    break
                if stream is None:
                    stream = sd.RawOutputStream(samplerate=chunk.sample_rate, channels=1, dtype="int16",
                                                device=audio_device())
                    stream.start()
                stream.write(robot(chunk.audio_int16_bytes, chunk.sample_rate) if self.fx else chunk.audio_int16_bytes)
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
