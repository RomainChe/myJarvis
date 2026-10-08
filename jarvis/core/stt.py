"""Reconnaissance vocale faster-whisper (Phase 4 étape 5), entrée seule : renvoie du texte, ne lance aucune action.

Modèle chargé seulement si tous ses fichiers du manifeste correspondent au SHA-256 (comme la voix et le réveil), hors
ligne (`local_files_only`). L'audio reste en mémoire (tableau float32) : ni fichier temporaire ni journal du texte (14, 20).
GPU d'abord (int8_float16) ; si CUDA manque (cublas absente, voir docs/VOIX.md §2bis) : repli CPU int8, plus lent.
"""
import json
import os
from pathlib import Path

import numpy as np

from jarvis.core.chat import TEXT_MAX
from jarvis.core.modelcheck import is_good
from jarvis.core.tts import ROOT

MODEL_DIR = "whisper-large-v3-turbo"
PROMPT = "Jarvis, salon, chambre, volets, clim, télé."  # court : il coûte du temps de décodage
ERR_MSG = "Reconnaissance vocale indisponible."


class STTError(Exception):
    """Message fixe : ne contient ni audio ni texte reconnu."""


class Transcriber:
    def __init__(self, *, models=ROOT / "models", manifest=ROOT / "models" / "MANIFEST.json", loader=None):
        self.models, self.manifest, self._loader = Path(models), Path(manifest), loader
        self._model, self.device, self._verified = None, None, False

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

    def _decode(self, audio):
        segments, _ = self._model.transcribe(audio, language="fr", beam_size=1, vad_filter=True, initial_prompt=PROMPT,
                                             condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()[:TEXT_MAX]

    def transcribe(self, audio: np.ndarray) -> str:
        """int16 mono 16 kHz -> texte (vide si rien d'intelligible). Toute erreur -> STTError au message fixe."""
        pcm = audio.astype(np.float32) / 32768.0
        try:
            for device in ("cpu",) if self.device == "cpu" else ("cuda", "cpu"):
                try:
                    if self._model is None:
                        self._load(device)
                    return self._decode(pcm)
                except STTError:
                    raise
                except Exception:  # CUDA absente ou GPU occupé : une seule retombée sur le CPU
                    if device == "cpu":
                        raise
                    self._model, self.device = None, "cpu"  # CUDA ne sera plus réessayé
        except STTError:
            raise
        except Exception:
            raise STTError(ERR_MSG) from None
        raise STTError(ERR_MSG)
