import importlib.util
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:  # extra `voice` absent (Core du mini-PC)
    raise unittest.SkipTest("numpy absent")

_spec = importlib.util.spec_from_file_location(
    "record_owner", Path(__file__).resolve().parents[1] / "scripts" / "wakeword" / "record_owner.py")
ro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ro)


class TrimTest(unittest.TestCase):
    audio = np.arange(48000, dtype=np.int16)  # fenêtre d'enregistrement : 3 s

    def test_rogne_avec_marge(self):
        clip = ro.trim(self.audio, [{"start": 8000, "end": 16000}])
        self.assertEqual((clip[0], len(clip)), (8000 - 1600, 8000 + 3200))

    def test_marge_bornee_au_debut(self):
        self.assertEqual(ro.trim(self.audio, [{"start": 500, "end": 4000}])[0], 0)

    def test_rien_entendu(self):
        self.assertIsNone(ro.trim(self.audio, []))

    def test_trop_long_refuse(self):
        self.assertIsNone(ro.trim(self.audio, [{"start": 0, "end": 4000}, {"start": 20000, "end": 40000}]))

    def test_mot_lent_garde(self):  # « Jarvis » dit lentement (~1,8 s) : ne doit plus être jeté
        self.assertIsNotNone(ro.trim(self.audio, [{"start": 1000, "end": 29000}]))


if __name__ == "__main__":
    unittest.main()
