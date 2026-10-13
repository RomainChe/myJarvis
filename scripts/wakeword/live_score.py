"""Essai au micro : affiche en direct le score des modèles de réveil (aucun audio gardé, aucune action lancée).

Usage : python scripts/wakeword/live_score.py [--bruit[=niveau]] [nom_de_modèle ...]   (défaut : hey_jarvis_v0.1 jarvis_fr)
--bruit : mélange en direct, dans le signal analysé seulement, des bruits AudioSet (musique, voix, ambiance) du dossier
d'entraînement ; niveau = RMS visé entre 0 et 1 (défaut 0.05, 0.1 = fort). Sert à tester au casque sans haut-parleur.
Micro : JARVIS_AUDIO_IN comme le reste de Jarvis. Ctrl+C pour finir ; le pic de chaque modèle est résumé.
"""
import os
import random
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from jarvis.core.mic import BLOCK, RATE  # noqa: E402
from jarvis.core.tts import audio_device  # noqa: E402


def _noise():
    folder = Path(os.environ.get("LOCALAPPDATA", ".")) / "jarvis-wakeword" / "data" / "background"
    files = sorted(folder.glob("*.wav"))
    if not files:
        sys.exit(f"aucun bruit dans {folder}")
    random.shuffle(files)
    parts = []
    for f in files[:60]:
        with wave.open(str(f)) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
        parts.append(x / max(float(np.sqrt(np.mean(x ** 2))), 1.0))  # RMS = 1 : le niveau s'applique ensuite
    return np.concatenate(parts)


def main(names, level=0.0):
    import sounddevice
    from openwakeword.model import Model
    d = ROOT / "models" / "openwakeword"
    model = Model(wakeword_models=[str(d / f"{n}.onnx") for n in names], inference_framework="onnx",
                  melspec_model_path=str(d / "melspectrogram.onnx"), embedding_model_path=str(d / "embedding_model.onnx"))
    peaks = dict.fromkeys(names, 0.0)
    noise, pos = (_noise(), 0) if level else (None, 0)
    if level:
        print(f"Bruit mélangé au signal analysé (niveau {level}).")
    print("Dis « Jarvis » (puis « hey Jarvis »), puis parle d'autre chose. Ctrl+C pour finir.")
    try:
        with sounddevice.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK,
                                     device=audio_device("JARVIS_AUDIO_IN")) as s:
            while True:
                data, _ = s.read(BLOCK)
                block = np.asarray(data, dtype=np.int16).reshape(-1)
                if noise is not None:
                    idx = (pos + np.arange(len(block))) % len(noise)
                    pos = (pos + len(block)) % len(noise)
                    block = np.clip(block + noise[idx] * level * 32768.0, -32768, 32767).astype(np.int16)
                scores = model.predict(block)
                for n in names:
                    peaks[n] = max(peaks[n], scores.get(n, 0.0))
                if max(scores.values()) >= 0.2:
                    print("  ".join(f"{n} {scores.get(n, 0.0):.2f}" for n in names))
    except KeyboardInterrupt:
        print("\nPics :", "  ".join(f"{n} {p:.2f}" for n, p in peaks.items()))


if __name__ == "__main__":
    args = sys.argv[1:]
    bruit = next((a for a in args if a.startswith("--bruit")), None)
    level = float(bruit.partition("=")[2] or 0.05) if bruit else 0.0
    main([a for a in args if not a.startswith("--")] or ["hey_jarvis_v0.1", "jarvis_fr"], level)
