"""Phase 4, étape 5 : Whisper (faux modèle) et chaîne micro -> texte -> Voice -> voix. Jamais de vrai modèle ni de micro."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from jarvis.core import stt
from jarvis.core.chat import TEXT_MAX
from jarvis.core.stt import STTError, Transcriber
from jarvis.core.voice import Listener

AUDIO = np.zeros(16000, dtype=np.int16)
ROOT = Path(__file__).resolve().parent.parent


class FakeModel:
    def __init__(self, text="allume le salon", fail=False):
        self.text, self.fail, self.calls = text, fail, []

    def transcribe(self, audio, **kw):
        self.calls.append((audio, kw))
        if self.fail:
            raise RuntimeError(f"boom {self.text}")
        return iter([SimpleNamespace(text=f" {self.text} ")]), None


def models_dir(good=True):
    tmp = Path(tempfile.mkdtemp())
    (tmp / stt.MODEL_DIR).mkdir()
    files = []
    for n in ("model.bin", "config.json"):
        p = f"{stt.MODEL_DIR}/{n}"
        (tmp / p).write_bytes(b"x")
        files.append({"path": p, "size": 1, "sha256": hashlib.sha256(b"x" if good else b"y").hexdigest()})
    (tmp / "m.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    return tmp


class TestTranscriber(unittest.TestCase):
    def make(self, loader, **kw):
        tmp = models_dir(**kw)
        return Transcriber(models=tmp, manifest=tmp / "m.json", loader=loader)

    def test_nominal_francais_et_float32(self):
        m = FakeModel()
        t = self.make(lambda path, dev, compute: m)
        self.assertEqual(t.transcribe(AUDIO), "allume le salon")
        audio, kw = m.calls[0]
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(kw["language"], "fr")
        self.assertEqual(t.device, "cuda")

    def test_repli_cpu_si_cuda_absente(self):
        calls = []

        def loader(path, dev, compute):
            calls.append((dev, compute))
            if dev == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found")
            return FakeModel()
        t = self.make(loader)
        self.assertEqual(t.transcribe(AUDIO), "allume le salon")
        self.assertEqual(calls, [("cuda", "int8_float16"), ("cpu", "int8")])
        t.transcribe(AUDIO)
        self.assertEqual(len(calls), 2)  # le CPU est gardé, pas de nouvel essai CUDA

    def test_modele_verifie_une_seule_fois(self):
        from unittest import mock
        t = self.make(lambda *a: FakeModel())
        with mock.patch("jarvis.core.stt.is_good", return_value=True) as ok:
            t.transcribe(AUDIO)
            t._model = None
            t.transcribe(AUDIO)
        self.assertEqual(ok.call_count, 2)  # 2 fichiers, une seule passe

    def test_panne_en_cours_de_decodage_repli_cpu(self):
        models = [FakeModel(fail=True), FakeModel()]
        t = self.make(lambda p, d, c: models.pop(0))
        self.assertEqual(t.transcribe(AUDIO), "allume le salon")
        self.assertEqual(t.device, "cpu")

    def test_modele_modifie_refuse(self):
        t = self.make(lambda *a: FakeModel(), good=False)
        with self.assertRaises(STTError) as cm:
            t.transcribe(AUDIO)
        self.assertIn("non vérifié", str(cm.exception))

    def test_modele_absent_du_manifeste_refuse(self):
        tmp = models_dir()
        (tmp / "m.json").write_text(json.dumps({"files": []}), encoding="utf-8")
        with self.assertRaises(STTError):
            Transcriber(models=tmp, manifest=tmp / "m.json", loader=lambda *a: FakeModel()).transcribe(AUDIO)

    def test_erreur_message_fixe_sans_texte(self):
        t = self.make(lambda *a: FakeModel(text="phrasesecrete42", fail=True))
        with self.assertRaises(STTError) as cm:
            t.transcribe(AUDIO)
        self.assertEqual(str(cm.exception), stt.ERR_MSG)
        self.assertNotIn("phrasesecrete42", str(cm.exception))

    def test_texte_borne(self):
        t = self.make(lambda *a: FakeModel(text="a" * 5000))
        self.assertEqual(len(t.transcribe(AUDIO)), TEXT_MAX)


class FakeVoice:
    def __init__(self, fail=False):
        self.said, self.handled, self.fail, self.gate = [], [], fail, None

    def handle(self, text):
        self.handled.append(text)
        if self.gate:
            self.gate.wait(3)
        if self.fail:
            raise RuntimeError("phrasesecrete42")
        return "C'est fait."

    def say(self, answer):
        self.said.append(answer)


class FakeSTT:
    def __init__(self, text="allume le salon"):
        self.text = text

    def transcribe(self, audio):
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


class TestListener(unittest.TestCase):
    def run_one(self, voice, stt_):
        shown = []
        ln = Listener(voice, stt_, lambda t, a: shown.append((t, a)))
        ln(AUDIO)
        ln._thread.join(3)
        return ln, shown

    def test_chaine_complete(self):
        v = FakeVoice()
        ln, shown = self.run_one(v, FakeSTT())
        self.assertEqual(v.handled, ["allume le salon"])
        self.assertEqual(v.said, ["C'est fait."])
        self.assertEqual(shown, [("allume le salon", "C'est fait.")])
        self.assertIsNone(ln.error)

    def test_texte_vide_pas_de_reponse(self):
        v = FakeVoice()
        self.run_one(v, FakeSTT(""))
        self.assertEqual((v.handled, v.said), ([], []))

    def test_erreur_stt_message_fixe(self):
        v = FakeVoice()
        ln, _ = self.run_one(v, FakeSTT(STTError(stt.ERR_MSG)))
        self.assertEqual(ln.error, stt.ERR_MSG)
        self.assertEqual(v.said, [])

    def test_erreur_interne_sans_texte(self):
        v = FakeVoice(fail=True)
        ln, _ = self.run_one(v, FakeSTT())
        self.assertEqual(ln.error, "Erreur vocale.")
        self.assertNotIn("phrasesecrete42", ln.error)

    def test_une_seule_phrase_a_la_fois(self):
        v = FakeVoice()
        v.gate = threading.Event()
        ln = Listener(v, FakeSTT())
        ln(AUDIO)
        t = ln._thread
        self.assertFalse(ln(AUDIO))  # jetée : la première est encore en traitement
        v.gate.set()
        t.join(3)
        self.assertEqual(len(v.handled), 1)
        ln(AUDIO)  # libre à nouveau
        ln._thread.join(3)
        self.assertEqual(len(v.handled), 2)


class TestHorsLigne(unittest.TestCase):
    def test_hf_hub_offline_pose_a_l_import(self):  # constat 9
        env = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}
        for mod in ("jarvis.server", "jarvis.__main__"):
            out = subprocess.run([sys.executable, "-c", f"import os, {mod}; print(os.environ.get('HF_HUB_OFFLINE'))"],
                                 cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.stdout.strip(), "1", out.stderr)


if __name__ == "__main__":
    unittest.main()
