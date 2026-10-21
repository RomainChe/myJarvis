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
        r = subprocess.run(["node", "--test", str(ROOT / "tests" / "tv_nav.test.js"), str(ROOT / "tests" / "tv_sitenav.test.js")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node absent : touches du lecteur TV non testées")
    def test_touches_lecteur_plein_ecran(self):
        r = subprocess.run(["node", "--test", str(ROOT / "tests" / "tv_lecteur.test.js")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_liaison_au_core_verrouillee(self):
        # La page ne choisit ni l'URL ni l'en-tête : routes fixes (la page n'en voit que deux), https vers *.ts.net, clé chiffrée, aucune redirection.
        link = (ROOT / "android-tv/app/src/main/java/fr/jarvis/tv/CoreLink.java").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'"(/api/[a-z]+)"', link), ["/api/token", "/api/tv", "/api/voice"])  # /api/token : renouvellement de la clé, jamais offert à la page
        self.assertIn('host.endsWith(".ts.net")', link)
        self.assertIn('"https".equals(u.getScheme())', link)
        self.assertIn("setInstanceFollowRedirects(false)", link)
        self.assertIn("AndroidKeyStore", link)
        self.assertIn("f.delete()", link)  # le fichier de configuration ne survit pas à l'import
        self.assertLess(link.index("f.length() > 2048"), link.index("f.delete()"))  # ...même trop gros (return dans le try)
        self.assertIn('setRequestProperty("Origin", cfg.getString("url"))', link)  # sans Origin, le Core refuse tout POST
        self.assertNotIn('"/".equals(u.getPath())', link)  # « / » final : l'URL deviendrait https://hôte//api/…
        self.assertNotRegex(link, r"Log\.|printStackTrace|System\.out")  # ni clé ni réponse dans les logs
        js = (TV_DIR / "tv.js").read_text(encoding="utf-8")
        self.assertRegex(js, r"textContent")
        self.assertIn("r.status === 401", js)  # clé expirée : on arrête de relancer le Core chaque minute
        self.assertIn("clearInterval(refreshTimer)", js)
        self.assertNotRegex(js, r"JarvisTV\.core\([^)]*\bhttp")  # la page ne passe jamais d'adresse

    def test_appui_long_sans_keydown_repete(self):
        # La WebView de la TV ne livre pas les keydown répétés : l'appui long passe par un minuteur.
        js = (TV_DIR / "tv.js").read_text(encoding="utf-8")
        self.assertNotIn("e.repeat", js)
        self.assertIn("HOLD_MS", js)

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
        hosts = (ROOT / "android-tv/app/src/main/java/fr/jarvis/tv/SiteHosts.java").read_text(encoding="utf-8")
        allowed = (set(re.findall(r'PACKAGES\.put\("([a-z]+)"', java)) | set(re.findall(r'case "([a-z]+)":', java))
                   | set(re.findall(r'HOSTS\.put\("([a-z]+)"', hosts)))
        self.assertTrue(tiles)
        self.assertEqual(tiles, allowed)
        bridge = (ROOT / "android-tv/app/src/main/java/fr/jarvis/tv/MainActivity.java").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"@JavascriptInterface\s+public \w+ (\w+)\(", bridge), ["core", "launch"], "deux points d'entrée JS, pas un de plus")
        manifest = (ROOT / "android-tv/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'<uses-permission android:name="([^"]+)"', manifest), ["android.permission.INTERNET", "android.permission.RECEIVE_BOOT_COMPLETED",
                                                                                            "android.permission.SYSTEM_ALERT_WINDOW"])

    def test_webview_bowd_sans_pont_et_non_exportee(self):
        # SiteActivity a le réseau : aucun pont JS, non exportée, navigation limitée à bowdtv.com, popups avalées.
        base = ROOT / "android-tv/app/src/main"
        site = (base / "java/fr/jarvis/tv/SiteActivity.java").read_text(encoding="utf-8")
        manifest = (base / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertNotIn("JavascriptInterface", site)
        self.assertRegex(manifest, r'android:name="\.SiteActivity"[^>]*android:exported="false"')
        hosts = (base / "java/fr/jarvis/tv/SiteHosts.java").read_text(encoding="utf-8")
        self.assertIn("SiteHosts.allowed(data.getHost())", site)
        self.assertIn("SiteHosts.within(siteHost, host)", site)
        self.assertIn('HOSTS.containsValue(host.toLowerCase(Locale.ROOT))', hosts)
        self.assertIn('endsWith("." + site)', hosts)
        self.assertIn('android:usesCleartextTraffic="false"', manifest)
        self.assertIn('"https".equals(data.getScheme())', site)
        self.assertNotIn("addJavascriptInterface", site)
        self.assertIn("onCreateWindow", site)
        self.assertIn("Passer la pub", site)
        self.assertIn("Application Android disponible", site)
        # Télécommande : script injecté sans pont (évalué dans la page, il ne peut rien appeler côté Java).
        self.assertIn('getAssets().open("sitenav.js")', site)
        nav = (base / "assets/sitenav.js").read_text(encoding="utf-8")
        self.assertTrue(nav.startswith("'use strict';"))
        self.assertNotIn("innerHTML", nav)
        # Écrans cachés de Bowd (aria-hidden) jamais visés ; un champ ne prend le focus (clavier) que sur OK.
        self.assertIn("e.closest('[aria-hidden=\"true\"],[inert]')", nav)
        self.assertIn("addEventListener('focusin'", nav)
        # Anneau collé à l'élément (aucune transition, qui le mettait en retard) ; focus repris au retour dans le site.
        ring_css = re.search(r"#jarvis-ring\{[^}]*\}", nav).group(0)
        self.assertNotIn("transition", ring_css)
        self.assertIn("addEventListener('popstate'", nav)
        # Retour confié à la page mais jamais bloqué, tap borné à la vue, zoom coupé (revue Sécurité C1/C2).
        self.assertIn("setSupportZoom(false)", site)
        self.assertIn("fx >= 0 && fx <= 1 && fy >= 0 && fy <= 1", site)
        self.assertIn("if (json == null ||", site)
        self.assertIn("jsBackAt < 800) nativeBack()", site)
        self.assertLess(site.index("jsBackAt = SystemClock.uptimeMillis()"), site.index("__jarvisNav.back()"))
        apps = (base / "java/fr/jarvis/tv/Apps.java").read_text(encoding="utf-8")

    def test_scripts_charges(self):
        html = (TV_DIR / "index.html").read_text(encoding="utf-8")
        for p in TV_DIR.glob("*.js"):
            self.assertIn(f'src="{p.name}"', html)
            self.assertTrue(p.read_text(encoding="utf-8").startswith("'use strict';"), p.name)


if __name__ == "__main__":
    unittest.main()
