"""Micro, mot de réveil et fin de phrase (Phase 4 étape 4). Entrée seule : aucune action n'est lancée ici.

Avant le réveil, chaque bloc est analysé par openWakeWord puis jeté (15). Après le réveil, la phrase est gardée dans un
tampon mémoire borné (14, 15 s) jusqu'au silence (VAD Silero de faster-whisper) puis remise à `on_utterance`, qui
l'oublie ensuite : aucun audio sur disque, aucun journal du contenu (le journal reçoit le score et la durée seulement).
Le micro est sourd pendant la lecture de Jarvis et un court moment après (anti-écho, `Speaker.ignore_until`).
Kill switch persistant : le fichier `mic_off` ; indicateur : `state` / `on_state`. Limite connue (18) : la voix seule
n'authentifie personne ; le plafond N0/N1 reste celui de `Voice`.
"""
import collections
import json
import os
import threading
import time
from pathlib import Path

import numpy as np

from jarvis.core.modelcheck import is_good
from jarvis.core.tts import ROOT, audio_device

RATE = 16000
BLOCK = 1280  # 80 ms : taille attendue par openWakeWord
WAKE_FILES = ("openwakeword/hey_jarvis_v0.1.onnx", "openwakeword/melspectrogram.onnx", "openwakeword/embedding_model.onnx")
THRESHOLD = 0.5
MAX_WAKES_PER_MIN = 4
MAX_UTTERANCE_S = 15  # tampon borné (14)
MAX_BLOCKS = MAX_UTTERANCE_S * RATE // BLOCK + 2  # plafond dur, indépendant de l'horloge
TAIL_S = 1.5  # fenêtre de la passe VAD une fois la parole entendue (coût constant)
FLAG = Path.home() / ".jarvis" / "mic_off"  # fixe : indépendant de JARVIS_DB, dossier protégé par les outils de fichiers
NO_SPEECH_S = 4  # réveil sans parole : on abandonne
SILENCE_S = 0.6  # fin de phrase
CHECK_EVERY = 6  # blocs entre deux passes VAD (~0,5 s)
SOURCE = "voix"
ERR_MSG = "Micro indisponible."
States = ("coupé", "veille", "écoute")


class MicError(Exception):
    """Message fixe : ne contient ni nom de périphérique ni audio."""


def threshold_from_env():
    try:
        return min(0.95, max(0.2, float(os.environ.get("JARVIS_WAKE_THRESHOLD", THRESHOLD))))
    except ValueError:
        return THRESHOLD


def silero_speech_end(audio):
    """int16 -> (parole détectée, silence final en échantillons). Silero est embarqué dans faster-whisper (MIT)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    spans = get_speech_timestamps(audio.astype(np.float32) / 32768.0, VadOptions(min_silence_duration_ms=int(SILENCE_S * 1000)))
    return (True, len(audio) - spans[-1]["end"]) if spans else (False, len(audio))


class Mic:
    def __init__(self, on_utterance, audit=None, speaker=None, on_state=None, *, flag=FLAG, models=ROOT / "models",
                 manifest=ROOT / "models" / "MANIFEST.json", threshold=THRESHOLD, sd=None, wake_loader=None,
                 speech_end=silero_speech_end, clock=time.monotonic):
        self.on_utterance, self.audit, self.speaker, self.on_state = on_utterance, audit, speaker, on_state
        self.flag, self.models, self.manifest, self.threshold = Path(flag), Path(models), Path(manifest), threshold
        self._sd, self._wake_loader, self._speech_end, self._clock = sd, wake_loader, speech_end, clock
        self._wake = None
        self._wakes = collections.deque()  # instants des réveils acceptés (limite de débit)
        self._limited = False
        self._buf, self._started, self._blocks, self._heard = None, 0.0, 0, False  # tampon de phrase (None = en veille)
        self.state, self.error = "veille", None
        self._stop = threading.Event()

    # --- kill switch persistant (16) ---
    def disabled(self):
        try:
            os.stat(self.flag)
            return True
        except FileNotFoundError:
            return False
        except OSError:  # illisible : on coupe (échec fermé)
            return True

    def disable(self):
        self.flag.parent.mkdir(parents=True, exist_ok=True)
        self.flag.touch()

    def enable(self):
        self.flag.unlink(missing_ok=True)

    def _set(self, state):
        if state != self.state:
            self.state = state
            if self.on_state:
                self.on_state(state)

    def _log(self, tool, args, result):
        try:
            if self.audit:
                self.audit.log(SOURCE, tool, args, None, "auto", result)
        except Exception:  # la boucle ne doit pas mourir sur le journal
            self.error = ERR_MSG

    def _load(self):
        if self._wake:
            return
        os.environ["HF_HUB_OFFLINE"] = "1"
        entries = {e["path"]: e for e in json.loads(self.manifest.read_text(encoding="utf-8"))["files"]}
        for path in WAKE_FILES:  # (23) vérifiés avant chargement
            e = entries.get(path)
            if e is None or not is_good(self.models / path, e["size"], e["sha256"]):
                raise MicError("modèle de réveil non vérifié")
        if self._wake_loader is None:
            from openwakeword.model import Model
            d = self.models / "openwakeword"
            self._wake_loader = lambda: Model(wakeword_models=[str(d / "hey_jarvis_v0.1.onnx")], inference_framework="onnx",
                                              melspec_model_path=str(d / "melspectrogram.onnx"),
                                              embedding_model_path=str(d / "embedding_model.onnx"))
        self._wake = self._wake_loader()

    def _accept_wake(self, now):
        while self._wakes and now - self._wakes[0] > 60:
            self._wakes.popleft()
        if len(self._wakes) >= MAX_WAKES_PER_MIN:
            if not self._limited:  # une seule ligne par rafale : pas de journal gonflable par une TV bavarde
                self._limited = True
                self._log("wake", None, "limité")
            return False
        self._limited = False
        self._wakes.append(now)
        return True

    def _end(self, audio, reason):
        self._buf = None
        self._set("veille")
        self._wake.reset()
        if audio is not None:
            self._log("mic", {"secondes": round(len(audio) / RATE, 1)}, reason)
            try:
                self.on_utterance(audio)
            except Exception:  # pas de trace : elle pourrait contenir du texte reconnu
                self.error = ERR_MSG

    def feed(self, block):
        """Un bloc int16 de BLOCK échantillons. Seule porte d'entrée de l'audio ; ne lève jamais."""
        try:
            self._feed(block)
        except Exception:
            self.error = ERR_MSG
            self._buf = None
            self._set("veille")

    def _feed(self, block):
        now = self._clock()
        if self.disabled():
            self._buf = None
            self._set("coupé")
            return
        if self.speaker is not None and now < self.speaker.ignore_until():  # (8) sourd pendant et après la lecture
            self._buf = None
            self._set("veille")
            if self._wake:
                self._wake.reset()
            return
        self._set("écoute" if self._buf is not None else "veille")
        if self._buf is None:
            self._load()
            scores = self._wake.predict(block)  # le bloc est jeté ensuite (15)
            if max(scores.values(), default=0.0) >= self.threshold and self._accept_wake(now):
                self._log("wake", None, "ok")
                self._buf, self._started, self._blocks, self._heard = [], now, 0, False
                self._set("écoute")
            return
        self._buf.append(block)
        self._blocks += 1
        elapsed = now - self._started
        full = elapsed >= MAX_UTTERANCE_S or self._blocks >= MAX_BLOCKS
        if self._blocks % CHECK_EVERY and not full:
            return
        audio = np.concatenate(self._buf)
        if self._heard and not full:  # parole déjà entendue : seule la queue est analysée
            _, silence = self._speech_end(audio[-int(TAIL_S * RATE):])
            speech = True
        else:
            speech, silence = self._speech_end(audio)
            self._heard = self._heard or speech
        if speech and silence >= SILENCE_S * RATE:
            self._end(audio, "ok")
        elif full:
            self._end(audio if self._heard else None, "tronqué")
        elif not speech and elapsed >= NO_SPEECH_S:
            self._end(None, "silence")

    def run(self):
        """Boucle bloquante jusqu'à `stop()`. Micro coupé = flux fermé (le voyant s'éteint). Erreur -> message fixe."""
        stream = None
        try:
            sd = self._sd or __import__("sounddevice")
            self._load()
            while not self._stop.is_set():
                if self.disabled():
                    if stream is not None:
                        stream.close()
                        stream = None
                    self._buf = None
                    self._set("coupé")
                    self._stop.wait(1)
                    continue
                if stream is None:
                    stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK,
                                            device=audio_device("JARVIS_AUDIO_IN"))
                    stream.start()
                    self._wake.reset()
                data, _ = stream.read(BLOCK)
                self.feed(np.asarray(data, dtype=np.int16).reshape(-1))
        except Exception:
            self.error = ERR_MSG
        finally:
            if stream is not None:
                stream.close()

    def stop(self):
        self._stop.set()
