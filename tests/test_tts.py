"""Phase 4, étape 3 : synthèse Piper et anti-écho (fausse voix, faux sounddevice : jamais de son réel)."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jarvis.core import gpu, tts
from jarvis.core.audit import Audit
from jarvis.core.chat import ANSWER_MAX
from jarvis.core.tts import Speaker
from jarvis.core.voice import Voice

SECRET = "phrasesecrete42"


class FakeVoice:
    def __init__(self, fail=False, delay=0.0):
        self.texts, self.fail, self.delay = [], fail, delay

    def synthesize(self, text, cfg):
        self.texts.append(text)
        self.cfg = cfg
        if self.fail:
            raise RuntimeError(f"boom {text}")
        for s in text.split("."):
            if s.strip():
                time.sleep(self.delay)
                yield SimpleNamespace(sample_rate=22050, audio_int16_bytes=s.strip().encode())


class FakeSD:
    def __init__(self):
        self.written, self.opened, self.aborted = [], [], 0

    def RawOutputStream(self, **kw):
        self.opened.append(kw)
        sd = self
        return SimpleNamespace(start=lambda: None, stop=lambda: None, close=lambda: None,
                               abort=lambda: setattr(sd, "aborted", sd.aborted + 1),
                               write=lambda b: sd.written.append(b))


class TTSTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = Audit(str(Path(self.tmp.name) / "a.db"))
        self.addCleanup(self.audit.db.close)
        self.sd, self.fv = FakeSD(), FakeVoice()
        p = mock.patch("jarvis.core.tts._fetch_models", return_value=SimpleNamespace(is_good=lambda *a: True))
        p.start()
        self.addCleanup(p.stop)

    def speaker(self, **kw):
        return Speaker(self.audit, sd=self.sd, loader=lambda path: self.fv, **kw)

    def rows(self):
        return self.audit.db.execute("SELECT source, tool, args, decision, result FROM audit").fetchall()

    def test_lecture_par_phrases(self):
        s = self.speaker()
        s.say("Un. Deux. Trois.")
        self.assertEqual(self.sd.written, [b"Un", b"Deux", b"Trois"])
        self.assertEqual(self.sd.opened[0]["samplerate"], 22050)
        self.assertEqual(self.fv.cfg.length_scale, 1.05)
        self.assertIsNone(s.error)

    def test_texte_trop_long_tronque(self):
        self.speaker().say("a" * (ANSWER_MAX + 500))
        self.assertEqual(len(self.fv.texts[0]), ANSWER_MAX)

    def test_texte_vide_ou_blanc_ignore(self):
        self.speaker().say("   ")
        self.assertEqual(self.fv.texts, [])
        self.assertEqual(self.rows(), [])

    def test_voix_refusee_si_hash_faux(self):
        with mock.patch("jarvis.core.tts._fetch_models", return_value=SimpleNamespace(is_good=lambda *a: False)):
            s = self.speaker()
            with self.assertRaises(tts.TTSError):
                s._load()
            s.say(SECRET)
        self.assertEqual(s.error, tts.ERR_MSG)
        self.assertEqual(self.sd.written, [])

    def test_erreur_generique_sans_fuite(self):
        self.fv.fail = True
        s = self.speaker()
        s.say(f"dis {SECRET}")
        self.assertEqual(s.error, tts.ERR_MSG)
        self.assertNotIn(SECRET, repr(self.rows()) + s.error)
        self.assertEqual(self.rows()[0][4], "erreur")

    def test_anti_echo(self):
        self.fv.delay = 0.2
        s = self.speaker(margin=0.4)
        s.say("Un. Deux.", block=False)
        time.sleep(0.05)
        self.assertTrue(s.is_speaking())
        self.assertEqual(s.ignore_until(), float("inf"))
        s._thread.join()
        self.assertFalse(s.is_speaking())
        end = time.monotonic()
        self.assertAlmostEqual(s.ignore_until(), end + 0.4, delta=0.3)
        self.assertGreater(s.ignore_until(), end)

    def test_stop_interrompt(self):
        self.fv.delay = 0.2
        s = self.speaker()
        s.say("Un. Deux. Trois. Quatre.", block=False)
        time.sleep(0.3)
        s.stop()
        self.assertFalse(s.is_speaking())
        self.assertLess(len(self.sd.written), 4)
        self.assertEqual(self.sd.aborted, 1)
        self.assertEqual(self.rows()[0][4], "interrompu")

    def test_audit_sans_texte(self):
        self.speaker().say(f"bonjour {SECRET}")
        src, tool, args, decision, result = self.rows()[0]
        self.assertEqual((src, tool, decision, result), ("voix", "tts", "auto", "ok"))
        self.assertIn('"len"', args)
        self.assertNotIn(SECRET, repr(self.rows()))
        self.assertEqual(len(self.rows()), 1)

    def test_aucun_fichier_cree(self):
        tmpdir, cwd = tempfile.mkdtemp(), tempfile.mkdtemp()
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(cwd)
        with mock.patch.object(tempfile, "tempdir", tmpdir):
            self.speaker().say("Un. Deux.")
        self.assertEqual(os.listdir(tmpdir), [])
        self.assertEqual(os.listdir(cwd), [])

    def test_peripherique(self):
        with mock.patch.dict(os.environ, {"JARVIS_AUDIO_OUT": "3"}):
            self.assertEqual(tts.audio_device(), 3)
        with mock.patch.dict(os.environ, {"JARVIS_AUDIO_OUT": ""}):
            self.assertIsNone(tts.audio_device())

    def test_voice_say_muet_et_desactive(self):
        chat = mock.Mock()  # pas de vrai Chat : il lie les niveaux globaux à ce journal
        Voice(chat).say("x")  # sans speaker : rien
        sp = mock.Mock()
        v = Voice(chat, sp)
        v.say("bonjour")
        sp.say.assert_called_once_with("bonjour")
        v.muted = True
        v.say("chut")
        sp.say.assert_called_once()


class GpuTest(unittest.TestCase):
    def test_path_prefixe_et_absent(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "nvidia" / "cublas" / "bin"
            d.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"PATH": "x"}), mock.patch("site.getsitepackages", return_value=[t]), \
                    mock.patch("site.getusersitepackages", return_value=str(Path(t) / "vide")):
                self.assertEqual(gpu.prepare_cuda_path(), [str(d)])
                self.assertEqual(os.environ["PATH"], str(d) + os.pathsep + "x")
                self.assertEqual(gpu.prepare_cuda_path(), [])  # déjà présent
            with mock.patch.dict(os.environ, {"PATH": "x"}), mock.patch("site.getsitepackages", return_value=[str(Path(t) / "non")]), \
                    mock.patch("site.getusersitepackages", return_value=str(Path(t) / "non")):
                self.assertEqual(gpu.prepare_cuda_path(), [])
                self.assertEqual(os.environ["PATH"], "x")


if __name__ == "__main__":
    unittest.main()
