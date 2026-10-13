"""Compare des modèles de réveil sur des clips jamais vus : rappel (voix réelle du propriétaire) et faux réveils
(mots proches synthétiques de negative_test + négatifs réels mis de côté).

Usage : python eval_heldout.py <modèle.onnx> [<modèle.onnx> ...]   (venv jarvis-wakeword)
"""
import os
import random
import sys
import wave
from pathlib import Path

import numpy as np

BASE = Path(os.environ["LOCALAPPDATA"]) / "jarvis-wakeword"
MODELS = Path(__file__).resolve().parents[2] / "models" / "openwakeword"
THRESHOLDS = (0.3, 0.5, 0.7, 0.9)


def peak(model, path):
    with wave.open(str(path)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    a = np.concatenate([np.zeros(16000, np.int16), a, np.zeros(16000, np.int16)])
    model.reset()
    best = 0.0
    for i in range(0, len(a) - 1279, 1280):
        best = max(best, max(model.predict(a[i:i + 1280]).values()))
    return best


def main(paths):
    from openwakeword.model import Model
    pos = sorted((BASE / "data" / "owner_heldout" / "positive").glob("*.wav"))
    neg = sorted((BASE / "data" / "owner_heldout" / "negative").glob("*.wav"))
    neg += random.Random(0).sample(sorted((BASE / "out" / "jarvis_fr" / "negative_test").glob("*.wav")), 300)
    for m in paths:
        model = Model(wakeword_models=[m], inference_framework="onnx",
                      melspec_model_path=str(MODELS / "melspectrogram.onnx"),
                      embedding_model_path=str(MODELS / "embedding_model.onnx"))
        p = np.array([peak(model, f) for f in pos])
        n = np.array([peak(model, f) for f in neg])
        print(Path(m).name, f"(positifs réels {len(p)}, négatifs {len(n)})")
        for t in THRESHOLDS:
            print(f"  seuil {t}: rappel {np.mean(p >= t):.0%}  faux réveils {np.mean(n >= t):.1%} ({int((n >= t).sum())})")


if __name__ == "__main__":
    main(sys.argv[1:])
