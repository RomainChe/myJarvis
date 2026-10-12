import importlib.util
import unittest
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "record_owner", Path(__file__).resolve().parents[1] / "scripts" / "wakeword" / "record_owner.py")
ro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ro)


class TrimTest(unittest.TestCase):
    audio = np.arange(32000, dtype=np.int16)

    def test_rogne_avec_marge(self):
        clip = ro.trim(self.audio, [{"start": 8000, "end": 16000}])
        self.assertEqual((clip[0], len(clip)), (8000 - 1600, 8000 + 3200))

    def test_marge_bornee_au_debut(self):
        self.assertEqual(ro.trim(self.audio, [{"start": 500, "end": 4000}])[0], 0)

    def test_rien_entendu(self):
        self.assertIsNone(ro.trim(self.audio, []))

    def test_trop_long_refuse(self):
        self.assertIsNone(ro.trim(self.audio, [{"start": 0, "end": 4000}, {"start": 20000, "end": 30000}]))


if __name__ == "__main__":
    unittest.main()
