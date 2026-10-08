"""Phase 4, étape 4 : micro, réveil, fin de phrase (faux modèle, faux VAD, fausse horloge : jamais de vrai micro)."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from jarvis.core import mic as micmod
from jarvis.core.audit import Audit
from jarvis.core.mic import BLOCK, RATE, Mic, MicError, threshold_from_env

BLOCK_AUDIO = np.zeros(BLOCK, dtype=np.int16)


class FakeWake:
    def __init__(self):
        self.score, self.resets = 0.0, 0

    def predict(self, block):
        return {"hey_jarvis_v0.1": self.score}

    def reset(self):
        self.resets += 1


class FakeSpeaker:
    def __init__(self):
        self.until = 0.0

    def ignore_until(self):
        return self.until


class MicBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.t = 100.0
        self.wake, self.heard, self.states = FakeWake(), [], []
        self.speech = (False, 0)  # réponse du faux VAD
        self.audit = Audit(str(self.tmp / "a.db"))
        self.speaker = FakeSpeaker()
        self.mic = Mic(self.heard.append, self.audit, self.speaker, self.states.append, flag=self.tmp / "mic_off",
                       models=self.tmp, manifest=self.tmp / "m.json", wake_loader=lambda: self.wake,
                       speech_end=lambda a: self.speech, clock=lambda: self.t)
        self.mic._load = lambda: setattr(self.mic, "_wake", self.wake)  # modèles vérifiés dans un test à part

    def feed(self, n=1, step=0.08):
        for _ in range(n):
            self.t += step
            self.mic.feed(BLOCK_AUDIO)

    def wake_up(self):
        self.wake.score = 0.9
        self.feed()
        self.wake.score = 0.0

    def log(self):
        return [r for r in self.audit.last(50)]


class TestMic(MicBase):
    def test_sans_reveil_rien_n_est_garde(self):
        self.feed(50)
        self.assertIsNone(self.mic._buf)
        self.assertEqual(self.heard, [])
        self.assertEqual(self.log(), [])

    def test_reveil_puis_phrase_remise_une_fois(self):
        self.wake_up()
        self.assertEqual(self.mic.state, "écoute")
        self.speech = (True, 0)
        self.feed(6)
        self.assertEqual(self.heard, [])  # encore en train de parler
        self.speech = (True, int(micmod.SILENCE_S * RATE))
        self.feed(6)
        self.assertEqual(len(self.heard), 1)
        self.assertEqual(len(self.heard[0]), 12 * BLOCK)
        self.assertEqual(self.mic.state, "veille")
        self.assertIsNone(self.mic._buf)  # tampon oublié
        self.assertEqual(self.states, ["écoute", "veille"])

    def test_journal_sans_contenu(self):
        self.wake_up()
        self.speech = (True, int(micmod.SILENCE_S * RATE))
        self.feed(6)
        flat = json.dumps(self.log(), default=str)
        self.assertIn("wake", flat)
        self.assertIn("secondes", flat)
        self.assertNotIn("sha256", flat)

    def test_reveil_sans_parole_abandonne(self):
        self.wake_up()
        self.feed(int(micmod.NO_SPEECH_S / 0.08) + 6)
        self.assertEqual(self.heard, [])
        self.assertEqual(self.mic.state, "veille")

    def test_tampon_borne(self):
        self.wake_up()
        self.speech = (True, 0)  # parle sans jamais s'arrêter
        self.feed(int(micmod.MAX_UTTERANCE_S / 0.08) + 10)
        self.assertEqual(len(self.heard), 1)
        self.assertLessEqual(len(self.heard[0]) / RATE, micmod.MAX_UTTERANCE_S + 0.6)
        self.assertEqual(self.mic.state, "veille")

    def test_seuil(self):
        self.wake.score = 0.49
        self.feed(5)
        self.assertEqual(self.mic.state, "veille")
        self.mic.threshold = 0.3
        self.feed()
        self.assertEqual(self.mic.state, "écoute")

    def test_limite_de_debit_des_reveils(self):
        for _ in range(micmod.MAX_WAKES_PER_MIN):
            self.wake_up()
            self.feed(int(micmod.NO_SPEECH_S / 0.08) + 6)  # abandon -> retour en veille
        self.wake_up()  # 5e réveil dans la minute
        self.assertEqual(self.mic.state, "veille")
        self.wake_up()
        self.assertEqual(sum("limité" in str(r) for r in self.log()), 1)  # une seule ligne par rafale
        self.t += 61
        self.wake_up()
        self.assertEqual(self.mic.state, "écoute")

    def test_kill_switch_persistant(self):
        self.mic.disable()
        self.wake.score = 0.9
        self.feed(3)
        self.assertEqual(self.mic.state, "coupé")
        self.assertEqual(self.log(), [])
        again = Mic(self.heard.append, flag=self.tmp / "mic_off")  # autre instance : le fichier persiste
        self.assertTrue(again.disabled())
        self.mic.enable()
        self.feed()
        self.assertEqual(self.mic.state, "écoute")

    def test_coupe_pendant_la_lecture_et_apres(self):
        self.speaker.until = self.t + 5  # Jarvis parle (ou vient de parler)
        self.wake.score = 0.9
        self.feed(10)
        self.assertEqual(self.mic.state, "veille")
        self.assertEqual(self.log(), [])
        self.t += 5
        self.feed()
        self.assertEqual(self.mic.state, "écoute")

    def test_lecture_en_cours_abandonne_la_phrase(self):
        self.wake_up()
        self.speaker.until = float("inf")
        self.feed()
        self.assertIsNone(self.mic._buf)
        self.assertEqual(self.heard, [])

    def test_erreur_du_rappel_sans_texte(self):
        def boom(audio):
            raise RuntimeError("phrasesecrete42")
        self.mic.on_utterance = boom
        self.wake_up()
        self.speech = (True, int(micmod.SILENCE_S * RATE))
        self.feed(6)
        self.assertEqual(self.mic.error, micmod.ERR_MSG)
        self.assertNotIn("phrasesecrete42", self.mic.error)
        self.assertEqual(self.mic.state, "veille")

    def test_erreur_vad_ne_leve_pas(self):
        self.mic._speech_end = lambda a: 1 / 0
        self.wake_up()
        self.feed(6)
        self.assertEqual(self.mic.error, micmod.ERR_MSG)
        self.assertEqual(self.mic.state, "veille")


class TestCorrectifsRevue(MicBase):
    def test_flag_fixe_sous_jarvis_home(self):  # constat 2 : protégé par la règle ~/.jarvis des outils de fichiers
        self.assertEqual(micmod.FLAG, Path.home() / ".jarvis" / "mic_off")

    def test_flag_illisible_coupe(self):  # constat 4
        from unittest import mock
        with mock.patch("os.stat", side_effect=PermissionError):
            self.assertTrue(self.mic.disabled())
        self.assertFalse(self.mic.disabled())

    def test_plafond_dur_de_blocs(self):  # constat 5 : horloge figée, le tampon reste borné
        self.wake_up()
        self.speech = (True, 0)
        for _ in range(micmod.MAX_BLOCKS + 50):
            self.mic.feed(BLOCK_AUDIO)  # sans avancer l'horloge
        self.assertEqual(len(self.heard), 1)
        self.assertLessEqual(len(self.heard[0]), micmod.MAX_BLOCKS * BLOCK)

    def test_vad_sur_la_queue_une_fois_la_parole_entendue(self):  # constat 6
        sizes = []
        def vad(a):
            sizes.append(len(a))
            return self.speech
        self.mic._speech_end = vad
        self.wake_up()
        self.speech = (True, 0)
        self.feed(60)
        self.assertGreater(len(sizes), 3)
        self.assertTrue(all(n <= int(micmod.TAIL_S * RATE) for n in sizes[1:]))

    def test_micro_coupe_ferme_le_flux(self):  # constat 3
        events = []
        class Stream:
            def start(self): events.append("start")
            def read(self, n):
                events.append("read")
                m.disable() if events.count("read") == 2 else None
                return np.zeros((n, 1), np.int16), False
            def close(self): events.append("close")
        class SD:
            def InputStream(self, **kw): return Stream()
        m = Mic(lambda a: None, flag=self.tmp / "off2", sd=SD(), wake_loader=lambda: self.wake)
        m._load = lambda: setattr(m, "_wake", self.wake)
        threading = __import__("threading")
        t = threading.Thread(target=m.run)
        t.start()
        for _ in range(100):
            if "close" in events:
                break
            __import__("time").sleep(0.02)
        self.assertEqual(m.state, "coupé")
        m.stop()
        t.join(3)
        self.assertEqual(events[:4], ["start", "read", "read", "close"])

    def test_peripherique_chiffres_unicode(self):  # constat 12
        from unittest import mock
        from jarvis.core.tts import audio_device
        with mock.patch.dict("os.environ", {"JARVIS_AUDIO_IN": "²"}):
            self.assertEqual(audio_device("JARVIS_AUDIO_IN"), "²")


class TestChargement(unittest.TestCase):
    def test_modele_non_verifie_refuse(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "m.json").write_text(json.dumps({"files": []}), encoding="utf-8")
        m = Mic(lambda a: None, flag=tmp / "off", models=tmp, manifest=tmp / "m.json", wake_loader=lambda: FakeWake())
        with self.assertRaises(MicError):
            m._load()

    def test_modele_modifie_refuse(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "openwakeword").mkdir()
        files = []
        for p in micmod.WAKE_FILES:
            (tmp / p).write_bytes(b"x")
            files.append({"path": p, "size": 1, "sha256": "0" * 64})
        (tmp / "m.json").write_text(json.dumps({"files": files}), encoding="utf-8")
        m = Mic(lambda a: None, flag=tmp / "off", models=tmp, manifest=tmp / "m.json", wake_loader=lambda: FakeWake())
        with self.assertRaises(MicError):
            m._load()

    def test_seuil_depuis_l_environnement(self):
        from unittest import mock
        for raw, want in (("0.7", 0.7), ("abc", 0.5), ("0.01", 0.2), ("5", 0.95)):
            with mock.patch.dict("os.environ", {"JARVIS_WAKE_THRESHOLD": raw}):
                self.assertEqual(threshold_from_env(), want)


class TestRun(unittest.TestCase):
    def test_erreur_materielle_message_fixe(self):
        class BadSD:
            def InputStream(self, **kw):
                raise OSError("Logitech PRO X introuvable")
        tmp = Path(tempfile.mkdtemp())
        m = Mic(lambda a: None, flag=tmp / "off", sd=BadSD(), wake_loader=lambda: FakeWake())
        m._load = lambda: None
        m.run()
        self.assertEqual(m.error, micmod.ERR_MSG)
        self.assertNotIn("Logitech", m.error)


if __name__ == "__main__":
    unittest.main()
