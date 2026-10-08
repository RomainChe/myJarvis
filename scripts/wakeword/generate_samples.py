"""Remplace piper-sample-generator pour openwakeword/train.py : fait dire les textes aux voix Piper locales
(françaises et anglaises), en 16 kHz mono. « jarvis » est décliné en variantes de prononciation par langue."""
import json
import os
import random
import uuid
import wave
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent.parent
VOICES = [  # (fichier .onnx, langue) ; le nombre de locuteurs vient du .json
    (HERE / "voices" / "fr_FR-tom-medium.onnx", "fr"),
    (HERE / "voices" / "fr_FR-upmc-medium.onnx", "fr"),
    (HERE / "voices" / "fr_FR-gilles-low.onnx", "fr"),
    (HERE / "voices" / "fr_FR-siwis-medium.onnx", "fr"),
    (HERE / "voices" / "fr_FR-mls-medium.onnx", "fr"),
    (HERE / "voices" / "en_US-libritts_r-medium.onnx", "en"),
    (HERE / "voices" / "en_GB-alan-medium.onnx", "en"),
]
WEIGHTS = [1, 1, 1, 1, 4, 4, 1]  # voix multi-locuteurs plus souvent : plus de timbres ; ~50 % fr / 50 % en
VARIANTS = {
    "fr": ["Jarvis", "Jarvis.", "Jarvis !", "Jarvis ?", "Jarvisse", "Djarvis", "Djarvisse", "Jarvice"],
    "en": ["Jarvis", "Jarvis.", "Jarvis!", "Jarvis?", "Jarviss"],
}
MAX_WORD_S, MAX_PHRASE_S, OVERSAMPLE = 1.5, 3.0, 1.5
WORKERS = 4  # synthèse sur le GPU (onnxruntime-gpu) : ~0,05 s par clip et par processus


def _speakers(onnx):
    return json.loads(Path(str(onnx) + ".json").read_text(encoding="utf-8")).get("num_speakers", 1)


def _say(text, lang):
    return random.choice(VARIANTS[lang]) if text.strip().lower() == "jarvis" else text


def _work(job):
    from piper import PiperVoice, SynthesisConfig
    onnx, lang, items = job
    import onnxruntime
    onnxruntime.preload_dlls()
    onnxruntime.set_default_logger_severity(3)
    voice = PiperVoice.load(str(onnx), use_cuda=True)
    sr, n = voice.config.sample_rate, _speakers(onnx)
    done = 0
    for text, path, ls, ns, nw in items:
        cfg = SynthesisConfig(speaker_id=random.randrange(n) if n > 1 else None, length_scale=ls,
                              noise_scale=ns, noise_w_scale=nw)
        audio = np.concatenate([c.audio_int16_array for c in voice.synthesize(_say(text, lang), cfg)] or [np.zeros(0, np.int16)])
        loud = np.flatnonzero(np.abs(audio.astype(np.int32)) > 0.05 * max(int(np.abs(audio.astype(np.int32)).max(initial=0)), 1))
        if loud.size == 0:
            continue
        audio = audio[max(loud[0] - sr // 20, 0):loud[-1] + sr // 10]  # silences rognés (50 ms avant, 100 ms après)
        if len(audio) > (MAX_WORD_S if text.strip().lower() == "jarvis" else MAX_PHRASE_S) * sr:
            continue  # voix qui déraille (gilles, mls) : exemple rejeté
        if sr != 16000:
            audio = np.clip(resample_poly(audio.astype(np.float32), 16000, sr), -32768, 32767).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            w.writeframes(audio.tobytes())
        done += 1
    return done


def generate_samples(text, max_samples, output_dir, file_names=None, length_scales=(0.75, 1.0, 1.25), **_):
    texts = [text] if isinstance(text, str) else list(text)
    n = int(max_samples * OVERSAMPLE)  # compense les rejets ; train.py ne fait que compter les fichiers
    names = [uuid.uuid4().hex + ".wav" for _ in range(n)]
    by_voice = {}
    for i in range(n):
        v = random.choices(range(len(VOICES)), WEIGHTS)[0]
        ls = random.choice(list(length_scales)) * random.uniform(0.9, 1.1)
        item = (random.choice(texts), os.path.join(output_dir, names[i]), ls, random.uniform(0.4, 1.0), random.uniform(0.5, 1.0))
        by_voice.setdefault(v, []).append(item)
    jobs = [(VOICES[v][0], VOICES[v][1], items[k:k + 500]) for v, items in by_voice.items() for k in range(0, len(items), 500)]
    with ProcessPoolExecutor(WORKERS) as ex:
        total = sum(ex.map(_work, jobs))
    print(f"{total}/{max_samples} clips -> {output_dir}", flush=True)
