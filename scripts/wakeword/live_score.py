"""Essai au micro : affiche en direct le score des modèles de réveil (aucun audio gardé, aucune action lancée).

Usage : python scripts/wakeword/live_score.py [nom_de_modèle ...]   (défaut : hey_jarvis_v0.1 jarvis_fr)
Micro : JARVIS_AUDIO_IN comme le reste de Jarvis. Ctrl+C pour finir ; le pic de chaque modèle est résumé.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from jarvis.core.mic import BLOCK, RATE  # noqa: E402
from jarvis.core.tts import audio_device  # noqa: E402


def main(names):
    import sounddevice
    from openwakeword.model import Model
    d = ROOT / "models" / "openwakeword"
    model = Model(wakeword_models=[str(d / f"{n}.onnx") for n in names], inference_framework="onnx",
                  melspec_model_path=str(d / "melspectrogram.onnx"), embedding_model_path=str(d / "embedding_model.onnx"))
    peaks = dict.fromkeys(names, 0.0)
    print("Dis « Jarvis » (puis « hey Jarvis »), puis parle d'autre chose. Ctrl+C pour finir.")
    try:
        with sounddevice.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK,
                                     device=audio_device("JARVIS_AUDIO_IN")) as s:
            while True:
                data, _ = s.read(BLOCK)
                scores = model.predict(np.asarray(data, dtype=np.int16).reshape(-1))
                for n in names:
                    peaks[n] = max(peaks[n], scores.get(n, 0.0))
                if max(scores.values()) >= 0.2:
                    print("  ".join(f"{n} {scores.get(n, 0.0):.2f}" for n in names))
    except KeyboardInterrupt:
        print("\nPics :", "  ".join(f"{n} {p:.2f}" for n, p in peaks.items()))


if __name__ == "__main__":
    main(sys.argv[1:] or ["hey_jarvis_v0.1", "jarvis_fr"])
