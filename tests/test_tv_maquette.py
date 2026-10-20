"""Maquette de l'interface TV (tv/) : navigation D-pad (via Node) et mêmes garde-fous que la PWA."""
import re
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
        for p in sorted(TV_DIR.glob("*.*")):  # tv/logos/ (local, hors Git) n'est pas du code
            text = p.read_text(encoding="utf-8")
            rules = {**FORBIDDEN_ANYWHERE, **(FORBIDDEN_JS if p.suffix == ".js" else {})}
            for name, rx in rules.items():
                self.assertIsNone(rx.search(text), f"{p.name} : {name}")

    def test_applis_dans_la_liste_blanche_de_l_apk(self):
        # Chaque tuile qui lance une appli doit avoir sa clé côté Java (Apps.java), et rien d'autre n'y est exposé.
        html = (TV_DIR / "index.html").read_text(encoding="utf-8")
        java = (ROOT / "android-tv/app/src/main/java/fr/jarvis/tv/Apps.java").read_text(encoding="utf-8")
        tiles = set(re.findall(r'data-app="([a-z]+)"', html))
        allowed = set(re.findall(r'(?:PACKAGES|SITES)\.put\("([a-z]+)"', java)) | set(re.findall(r'case "([a-z]+)":', java))
        self.assertTrue(tiles)
        self.assertEqual(tiles, allowed)
        bridge = (ROOT / "android-tv/app/src/main/java/fr/jarvis/tv/MainActivity.java").read_text(encoding="utf-8")
        self.assertEqual(bridge.count("@JavascriptInterface"), 1, "un seul point d'entrée JS")
        manifest = (ROOT / "android-tv/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'<uses-permission android:name="([^"]+)"', manifest), ["android.permission.INTERNET"])

    def test_webview_bowd_sans_pont_et_non_exportee(self):
        # SiteActivity a le réseau : aucun pont JS, non exportée, navigation limitée à bowdtv.com, popups avalées.
        base = ROOT / "android-tv/app/src/main"
        site = (base / "java/fr/jarvis/tv/SiteActivity.java").read_text(encoding="utf-8")
        manifest = (base / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertNotIn("JavascriptInterface", site)
        self.assertRegex(manifest, r'android:name="\.SiteActivity"[^>]*android:exported="false"')
        self.assertIn('host.endsWith("." + siteHost)', site)
        self.assertIn('android:usesCleartextTraffic="false"', manifest)
        self.assertIn('"https".equals(data.getScheme())', site)
        self.assertNotIn("addJavascriptInterface", site)
        self.assertIn("onCreateWindow", site)
        self.assertIn("Passer la pub", site)
        apps = (base / "java/fr/jarvis/tv/Apps.java").read_text(encoding="utf-8")

    def test_scripts_charges(self):
        html = (TV_DIR / "index.html").read_text(encoding="utf-8")
        for p in TV_DIR.glob("*.js"):
            self.assertIn(f'src="{p.name}"', html)
            self.assertTrue(p.read_text(encoding="utf-8").startswith("'use strict';"), p.name)


if __name__ == "__main__":
    unittest.main()
