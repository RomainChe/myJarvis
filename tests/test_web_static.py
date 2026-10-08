"""Garde-fous de la PWA (jarvis/web/) : motifs interdits par la revue Sécurité d'entrée de Phase 3 (XSS, CSP, secrets)."""
import json
import re
import unittest

from jarvis.server import WEB_DIR, WEB_TYPES

FORBIDDEN_JS = {
    "innerHTML/outerHTML/insertAdjacentHTML": re.compile(r"innerHTML|outerHTML|insertAdjacentHTML"),
    "document.write": re.compile(r"document\s*\.\s*write"),
    "eval / new Function": re.compile(r"\beval\s*\(|new\s+Function\b"),
    "dangerouslySetInnerHTML": re.compile(r"dangerouslySetInnerHTML"),
    "setTimeout/setInterval avec une chaîne": re.compile(r"set(Timeout|Interval)\(\s*[\"'`]"),
    "localStorage/sessionStorage (le token va dans IndexedDB)": re.compile(r"localStorage|sessionStorage"),
    "console.* (aucune donnée dans les logs)": re.compile(r"console\s*\.\s*(log|debug|info|warn|error)"),
    "style en ligne (CSP style-src 'self')": re.compile(r"setAttribute\(\s*[\"']style[\"']|\.cssText\s*=|\.style\.cssText"),
    "import() distant": re.compile(r"import\(\s*[\"'`]https?:"),
}
FORBIDDEN_ANYWHERE = {
    "ressource externe": re.compile(r"https?://(?!www\.w3\.org/)", re.IGNORECASE),
    "adresse IP": re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"),
    "nom Tailscale": re.compile(r"\.ts\.net", re.IGNORECASE),
}


def files():
    return sorted(p for p in WEB_DIR.iterdir() if p.is_file())


class WebStaticTest(unittest.TestCase):
    def test_dossier_plat_et_extensions_servies(self):
        self.assertTrue(WEB_DIR.is_dir())
        for p in WEB_DIR.iterdir():
            self.assertTrue(p.is_file(), f"sous-dossier non servi : {p.name}")
            self.assertIn(p.suffix, WEB_TYPES, p.name)

    def test_fichiers_attendus(self):
        names = {p.name for p in files()}
        self.assertTrue({"index.html", "app.css", "app.js", "sw.js", "manifest.webmanifest", "icon.svg"} <= names)

    def test_motifs_interdits_dans_le_js(self):
        for p in files():
            if p.suffix != ".js":
                continue
            text = p.read_text(encoding="utf-8")
            for label, pattern in FORBIDDEN_JS.items():
                self.assertIsNone(pattern.search(text), f"{p.name} : {label}")

    def test_motifs_interdits_partout(self):
        for p in files():
            text = p.read_text(encoding="utf-8")
            for label, pattern in FORBIDDEN_ANYWHERE.items():
                self.assertIsNone(pattern.search(text), f"{p.name} : {label}")

    def test_html_sans_script_ni_style_en_ligne(self):
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        for tag in re.findall(r"<script\b[^>]*>", html, re.IGNORECASE):
            self.assertIn("src=", tag, "script en ligne")
        for label, pattern in {"<style>": re.compile(r"<style\b", re.IGNORECASE),
                               "attribut style=": re.compile(r"\sstyle\s*=", re.IGNORECASE),
                               "gestionnaire on…=": re.compile(r"\son[a-z]+\s*=", re.IGNORECASE),
                               "javascript:": re.compile(r"javascript:", re.IGNORECASE)}.items():
            self.assertIsNone(pattern.search(html), label)

    def test_service_worker_ne_met_pas_l_api_en_cache(self):
        sw = (WEB_DIR / "sw.js").read_text(encoding="utf-8")
        self.assertIn("/api/", sw)  # un contournement explicite des routes d'API existe
        self.assertNotRegex(sw, r"addAll\([^)]*api")

    def test_manifest_valide(self):
        manifest = json.loads((WEB_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))
        for key in ("name", "short_name", "start_url", "display", "theme_color", "background_color", "icons"):
            self.assertIn(key, manifest)
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertTrue(manifest["icons"])


if __name__ == "__main__":
    unittest.main()
