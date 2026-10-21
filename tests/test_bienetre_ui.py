"""Onglet Bien-être : score et icônes côté PWA (Node)."""
import shutil
import subprocess
import unittest
from pathlib import Path


class BienetreUiTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node absent : score Bien-être non testé")
    def test_score_et_icones(self):
        r = subprocess.run(["node", "--test", str(Path(__file__).with_name("bienetre.test.js"))], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
