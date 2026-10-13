"""Vérifie avec Whisper (modèle du projet) que chaque clip généré dit bien « Jarvis » ; déplace les autres.

Usage (racine du dépôt, venv du projet) : python scripts/wakeword/verify_clips.py <dossier>
Les clips refusés vont dans <dossier>/_rejetes (rien n'est supprimé).
"""
import re
import shutil
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jarvis.core.stt import Transcriber  # noqa: E402

OK = re.compile(r"j[ae]?r?v[iy]s|djarvis|jarvice", re.I)


def main(folder):
    t = Transcriber(gaming=lambda: False)  # GPU ; passer à True pour forcer le CPU
    bad = folder / "_rejetes"
    kept = rejected = 0
    for p in sorted(folder.glob("*.wav")):
        with wave.open(str(p)) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        text = t.transcribe(audio)
        if OK.search(text):
            kept += 1
        else:
            bad.mkdir(exist_ok=True)
            shutil.move(p, bad / p.name)
            rejected += 1
            print(f"rejeté : {p.name} -> « {text} »")
    print(f"{kept} gardés, {rejected} rejetés")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
