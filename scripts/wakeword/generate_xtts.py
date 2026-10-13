"""Clone la voix du propriétaire (et d'autres références) avec XTTS-v2 pour générer des « Jarvis » d'entraînement.

Usage (venv jarvis-wakeword) : python generate_xtts.py <dossier_sortie> <nombre> [dossier_refs ...]
Références par défaut : %LOCALAPPDATA%/jarvis-wakeword/data/owner/positive. Sortie : WAV 16 kHz mono, rognés,
clips > 1,5 s rejetés. Les clips restent hors du dépôt (voix = donnée personnelle).
"""
import os
import random
import sys
import uuid
import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

os.environ.setdefault("COQUI_TOS_AGREED", "1")  # licence CPML, usage personnel non commercial
BASE = Path(os.environ.get("LOCALAPPDATA", ".")) / "jarvis-wakeword" / "data"
TEXTS = ["Jarvis", "Jarvis.", "Jarvis !", "Jarvis ?", "Jarvis,", "Hé Jarvis", "Ok Jarvis", "Dis Jarvis"]
MAX_S = 1.5


def trim(audio, sr):
    peak = np.abs(audio).max(initial=0)
    loud = np.flatnonzero(np.abs(audio) > 0.05 * max(peak, 1e-6))
    if loud.size == 0:
        return None
    return audio[max(loud[0] - sr // 20, 0):loud[-1] + sr // 10]


def main(out, n, ref_dirs):
    from TTS.api import TTS
    refs = [str(p) for d in ref_dirs for p in Path(d).glob("*.wav")]
    if not refs:
        sys.exit(f"aucune référence dans {ref_dirs}")
    out.mkdir(parents=True, exist_ok=True)
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")
    done = tries = 0
    while done < n and tries < n * 4:
        tries += 1
        text = random.choice(TEXTS)
        ref = random.sample(refs, min(3, len(refs)))  # 3 références mélangées : timbre moyen, plus de variété
        wav = tts.tts(text=text, language="fr", speaker_wav=ref, speed=random.uniform(0.85, 1.25),
                      temperature=random.uniform(0.5, 0.9))
        audio = np.asarray(wav, dtype=np.float32)
        audio = trim(audio, 24000)
        if audio is None or len(audio) > MAX_S * 24000:
            continue
        audio = resample_poly(audio, 2, 3)  # 24 kHz -> 16 kHz
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        with wave.open(str(out / f"xtts_{uuid.uuid4().hex}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            w.writeframes(pcm.tobytes())
        done += 1
    print(f"{done}/{n} clips -> {out} ({tries} essais)", flush=True)


if __name__ == "__main__":
    dirs = sys.argv[3:] or [str(BASE / "owner" / "positive")]
    main(Path(sys.argv[1]), int(sys.argv[2]), dirs)
