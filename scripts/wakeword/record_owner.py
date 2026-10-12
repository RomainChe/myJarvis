"""Enregistrement guidé de la voix du propriétaire pour réentraîner le mot de réveil.

Usage (dans un terminal à part, micro du casque) : python scripts/wakeword/record_owner.py [nb_jarvis]
Chaque fenêtre de 2 s est rognée sur la parole (VAD Silero) puis écrite en WAV 16 kHz dans
%LOCALAPPDATA%/jarvis-wakeword/data/owner/{positive,negative} : hors du dépôt (donnée personnelle).
Le bruit de fond n'est pas à enregistrer : l'entraînement mélange déjà bruits et réverbérations.
"""
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

RATE, WINDOW_S, MARGIN_S, MAX_S = 16000, 2.0, 0.1, 1.5
OUT = Path(os.environ.get("LOCALAPPDATA", ".")) / "jarvis-wakeword" / "data" / "owner"
STYLES = ["normal", "plus fort", "plus doucement", "vite", "lentement", "en tournant la tête", "fatigué, mou",
          "comme une question", "en souriant", "normal"]
NEGATIVES = ["jardin", "j'arrive", "j'avais", "ça va", "Gervais", "Travis", "Elvis", "Paris", "javel", "jadis",
             "j'ai vu", "service", "Charlie", "tarif", "avis", "allume le salon", "bonne nuit", "merci",
             "quelle heure est-il", "ferme les volets"]


def trim(audio, spans):
    """int16 + segments VAD (échantillons) -> clip rogné avec marge, ou None si vide / trop long."""
    if not spans:
        return None
    m = int(MARGIN_S * RATE)
    clip = audio[max(0, spans[0]["start"] - m):min(len(audio), spans[-1]["end"] + m)]
    return clip if len(clip) <= MAX_S * RATE else None


def _spans(audio):
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    return get_speech_timestamps(audio.astype(np.float32) / 32768.0, VadOptions(min_silence_duration_ms=200))


def _save(path, clip):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(clip.astype(np.int16).tobytes())


def _session(sd, label, words, device):
    folder = OUT / label
    folder.mkdir(parents=True, exist_ok=True)
    stamp, kept = time.strftime("%Y%m%d%H%M%S"), 0
    for i, word in enumerate(words, 1):
        print(f"  [{i}/{len(words)}]  >>>  {word}", flush=True)
        a = sd.rec(int(WINDOW_S * RATE), samplerate=RATE, channels=1, dtype="int16", device=device)
        sd.wait()
        clip = trim(a[:, 0], _spans(a[:, 0]))
        if clip is None:
            print("      (rien entendu ou trop long : ignoré)")
            continue
        _save(folder / f"{stamp}_{i:03d}.wav", clip)
        kept += 1
    print(f"{kept}/{len(words)} clips gardés -> {folder}\n")


def main(n=100):
    import sounddevice as sd
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    raw = os.environ.get("JARVIS_AUDIO_IN")
    device = int(raw) if raw and raw.isdigit() else raw
    per_style = max(1, n // len(STYLES))
    print(f"Partie 1 : dis « Jarvis » à chaque >>> ({per_style * len(STYLES)} fois, 2 s chacun).")
    for style in STYLES:
        input(f"\nStyle : {style}. Entrée pour commencer...")
        _session(sd, "positive", [f"Jarvis  ({style})"] * per_style, device)
    input("Partie 2 : lis le mot affiché (PAS « Jarvis »). Entrée pour commencer...")
    _session(sd, "negative", NEGATIVES, device)
    print("Terminé. Rien n'est envoyé : les clips restent sur ce PC.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
