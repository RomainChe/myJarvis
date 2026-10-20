"""Maquette de l'interface TV (tv/) : navigation D-pad (via Node) et mêmes garde-fous que la PWA."""
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_web_static import FORBIDDEN_ANYWHERE, FORBIDDEN_JS

ROOT = Path(__file__).resolve().parent.parent
TV_DIR = ROOT / "tv"


class TvMaquetteTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node absent : navigation TV non testée")
    def test_navigation_dpad(self):
        r = subprocess.run(["node", "--test", str(ROOT / "tests" / "tv_nav.test.js")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_garde_fous(self):
        for p in sorted(TV_DIR.iterdir()):
            text = p.read_text(encoding="utf-8")
            rules = {**FORBIDDEN_ANYWHERE, **(FORBIDDEN_JS if p.suffix == ".js" else {})}
            for name, rx in rules.items():
                self.assertIsNone(rx.search(text), f"{p.name} : {name}")

    def test_scripts_charges(self):
        html = (TV_DIR / "index.html").read_text(encoding="utf-8")
        for p in TV_DIR.glob("*.js"):
            self.assertIn(f'src="{p.name}"', html)
            self.assertTrue(p.read_text(encoding="utf-8").startswith("'use strict';"), p.name)


if __name__ == "__main__":
    unittest.main()
