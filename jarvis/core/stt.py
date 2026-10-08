"""Reconnaissance vocale faster-whisper (Phase 4 étape 5), entrée seule : renvoie du texte, ne lance aucune action.

Modèle chargé seulement si tous ses fichiers du manifeste correspondent au SHA-256 (comme la voix et le réveil), hors
ligne (`local_files_only`). L'audio reste en mémoire (tableau float32) : ni fichier temporaire ni journal du texte (14, 20).
GPU d'abord (int8_float16) ; si CUDA manque (cublas absente, voir docs/VOIX.md §2bis) : repli CPU int8, plus lent.
Mode jeu (`games.detect`, résultat gardé 5 s) : le modèle GPU est déchargé et la phrase passe sur le CPU, pour ne pas
prendre la VRAM du jeu ; le GPU n'est rechargé qu'après 60 s sans jeu détecté (pas de va-et-vient de 6 s par phrase).
"""
import json
import os
import time
from pathlib import Path

import numpy as np

from jarvis.core import games
from jarvis.core.chat import TEXT_MAX
from jarvis.core.modelcheck import is_good
from jarvis.core.tts import ROOT

MODEL_DIR = "whisper-large-v3-turbo"
PROMPT = "Jarvis, salon, chambre, volets, clim, télé."  # court : il coûte du temps de décodage
GAME_CHECK_S, GAME_HOLD_S = 5, 60
ERR_MSG = "Reconnaissance vocale indisponible."


class STTError(Exception):
    """Message fixe : ne contient ni audio ni texte reconnu."""


class Transcriber:
    def __init__(self, *, models=ROOT / "models", manifest=ROOT / "models" / "MANIFEST.json", loader=None,
                 gaming=games.detect, clock=time.monotonic):
        self.models, self.manifest, self._loader, self.gaming = Path(models), Path(manifest), loader, gaming
        self._clock, self._checked, self._game_until = clock, None, 0.0
        self._model, self.device, self._verified, self._cuda_failed = None, None, False, False

    def _load(self, device):
        os.environ["HF_HUB_OFFLINE"] = "1"
        if not self._verified:  # une seule fois par processus : model.bin pèse 1,6 Go à hacher
            entries = json.loads(self.manifest.read_text(encoding="utf-8"))["files"]
            files = [e for e in entries if e["path"].startswith(MODEL_DIR + "/")]
            if not files or not all(is_good(self.models / e["path"], e["size"], e["sha256"]) for e in files):
                raise STTError("modèle de reconnaissance non vérifié")
            self._verified = True
        if self._loader is None:
            from jarvis.core.gpu import prepare_cuda_path
            prepare_cuda_path()  # avant l'import de faster_whisper
            from faster_whisper import WhisperModel
            self._loader = lambda path, dev, compute: WhisperModel(path, device=dev, compute_type=compute, local_files_only=True)
        self._model = self._loader(str(self.models / MODEL_DIR), device, "int8_float16" if device == "cuda" else "int8")
        self.device = device

    def _cpu_only(self):
        now = self._clock()
        if self._checked is None or now - self._checked >= GAME_CHECK_S:
            self._checked = now
            if self.gaming():
                self._game_until = now + GAME_HOLD_S
        return self._cuda_failed or now < self._game_until

    def _decode(self, audio):
        segments, _ = self._model.transcribe(audio, language="fr", beam_size=1, vad_filter=True, initial_prompt=PROMPT,
                                             condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()[:TEXT_MAX]

    def transcribe(self, audio: np.ndarray) -> str:
        """int16 mono 16 kHz -> texte (vide si rien d'intelligible). Toute erreur -> STTError au message fixe."""
        pcm = audio.astype(np.float32) / 32768.0
        try:
            cpu_only = self._cpu_only()
            if self._model is not None and self.device != ("cpu" if cpu_only else "cuda"):
                self._model, self.device = None, None  # décharge (entrée ou sortie du mode jeu)
            for device in ("cpu",) if cpu_only else ("cuda", "cpu"):
                try:
                    if self._model is None:
                        self._load(device)
                    return self._decode(pcm)
                except STTError:
                    raise
                except Exception:  # CUDA absente ou GPU occupé : une seule retombée sur le CPU
                    if device == "cpu":
                        raise
                    self._model, self._cuda_failed = None, True  # CUDA ne sera plus réessayé
        except STTError:
            raise
        except Exception:
            raise STTError(ERR_MSG) from None
        raise STTError(ERR_MSG)
