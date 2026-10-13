"""Remonte le corpus d'entraînement « Jarvis » : peu de Piper, beaucoup de voix réelle et clonée.

Usage (venv jarvis-wakeword) : python build_corpus.py [nb_piper=6000] [variantes_par_clip=12]
 - positive_train : `nb_piper` clips Piper gardés (le reste est déplacé dans _piper_extra, réversible),
   clips réels du propriétaire x variantes (vitesse/hauteur/gain), clips XTTS déjà vérifiés par Whisper.
 - negative_train : mots négatifs du propriétaire x variantes.
 - les deux fichiers de features sont mis de côté (.bak) : train.py les recalcule (il saute l'étape sinon).
Tout reste hors du dépôt (voix = donnée personnelle).
"""
import os
import random
import shutil
import sys
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

BASE = Path(os.environ["LOCALAPPDATA"]) / "jarvis-wakeword"
OUT = BASE / "out" / "jarvis_fr"
OWNER, XTTS = BASE / "data" / "owner", BASE / "data" / "xtts"


def read(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)


def write(p, x):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(np.clip(x, -32768, 32767).astype(np.int16).tobytes())


def variants(x, n):
    """Le clip tel quel, puis n-1 versions : vitesse/hauteur ±15 % (rééchantillonnage) et gain."""
    yield x
    for _ in range(n - 1):
        f = Fraction(random.uniform(0.85, 1.15)).limit_denominator(20)
        yield resample_poly(x, f.numerator, f.denominator) * random.uniform(0.5, 1.2)


def main(n_piper=6000, n_var=12):
    pos, neg = OUT / "positive_train", OUT / "negative_train"
    extra = OUT / "_piper_extra"
    extra.mkdir(exist_ok=True)
    for old in list(pos.glob("owner_*")) + list(pos.glob("xtts_*")) + list(neg.glob("owner_*")):
        old.unlink()
    for extra_file in extra.glob("*.wav"):  # repartir de tous les Piper pour un tirage neuf
        shutil.move(extra_file, pos / extra_file.name)
    piper = sorted(pos.glob("*.wav"))
    random.shuffle(piper)
    for p in piper[n_piper:]:
        shutil.move(p, extra / p.name)
    n_real = n_x = n_neg = 0
    for p in sorted((OWNER / "positive").glob("*.wav")):
        for i, v in enumerate(variants(read(p), n_var)):
            write(pos / f"owner_{p.stem}_{i:02d}.wav", v)
            n_real += 1
    for p in sorted(XTTS.glob("*.wav")):  # _rejetes/ est un sous-dossier : ignoré
        shutil.copy(p, pos / p.name)
        n_x += 1
    for p in sorted((OWNER / "negative").glob("*.wav")):
        for i, v in enumerate(variants(read(p), n_var)):
            write(neg / f"owner_{p.stem}_{i:02d}.wav", v)
            n_neg += 1
    for f in ("positive_features_train.npy", "negative_features_train.npy"):
        if (OUT / f).exists():
            os.replace(OUT / f, OUT / (f + ".bak"))
    print(f"positive_train : {min(n_piper, len(piper))} Piper + {n_real} réels + {n_x} XTTS ; negative_train : +{n_neg} réels")


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:3]))
