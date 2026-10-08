"""Onglet Veille IA : extraction générique des envois .eml, liens non https et HTML hostile écartés, route authentifiée et journalisée."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import veille
from tests.test_server import ServerBase


def issue(subject="[Veille IA] Semaine 40", body="", date="Mon, 5 Oct 2026 00:00:10 -0700") -> bytes:
    html = (f"<html><head><title>{subject}</title><style>p{{color:red}}</style></head><body>"
            "<h1>Veille IA</h1><p>1. Sonnet 5.5 sort : plus rapide et moins cher.</p>"
            "<p>Source : <a href='https://www.anthropic.com/news'>Anthropic News</a> et "
            "<a href=\"https://www.anthropic.com/news\">doublon</a></p>"
            f"<ul><li>Deuxième point</li></ul>{body}</body></html>")
    return (f"Date: {date}\nSubject: {subject}\nMIME-Version: 1.0\nContent-Type: text/html; charset=UTF-8\n\n{html}").encode("utf-8")


def folder(files: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    for n, raw in files.items():
        (root / n).write_bytes(raw)
    return root


class VeilleTest(unittest.TestCase):
    def test_nominal(self):
        s = veille.snapshot(folder({"a.eml": issue(), "b.eml": issue("[Veille Plugins] Semaine 40 – Top 3"),
                                    "c.eml": issue("[Veille IA] Semaine 39")}))
        self.assertTrue(s["configured"])
        self.assertEqual([(i["kind"], i["week"]) for i in s["issues"]], [("plugins", 40), ("actus", 40), ("actus", 39)])
        first = s["issues"][1]
        self.assertEqual(first["blocks"][:2], ["Veille IA", "1. Sonnet 5.5 sort : plus rapide et moins cher."])
        self.assertNotIn("p{color:red}", " ".join(first["blocks"]))  # style et title ignorés
        self.assertEqual(first["links"], [{"url": "https://www.anthropic.com/news", "host": "www.anthropic.com", "label": "Anthropic News"}])

    def test_liens_dangereux_et_limites(self):
        body = ("<a href='javascript:alert(1)'>x</a><a href='http://clair.example/'>y</a><a href='https://u:p@evil.example/'>z</a>"
                "<a href='data:text/html,x'>d</a><a href='//evil.example/'>r</a>"
                + "".join(f"<a href='https://s{i}.example/'>s{i}</a>" for i in range(30)) + "<p>" + "x" * 5000 + "</p>")
        i = veille.snapshot(folder({"a.eml": issue(body=body)}))["issues"][0]
        self.assertTrue(all(l["url"].startswith("https://s") or l["host"] == "www.anthropic.com" for l in i["links"]))
        self.assertEqual(len(i["links"]), veille.MAX_LINKS)
        self.assertTrue(all(len(b) <= veille.BLOCK for b in i["blocks"]) and len(i["blocks"]) <= veille.MAX_BLOCKS)

    def test_domaine_affiche_doit_etre_la_destination(self):
        body = ("<a href='https://evil.com\\.bon.com/x'>a</a><a href='https://bon.com/a b'>b</a><a href='https://bücher.example/'>c</a>"
                "<a href='https://xn--bcher-kva.example/'>d</a><a href='https://EXEMPLE.org/Page'>e</a>")
        links = veille.snapshot(folder({"a.eml": issue(body=body)}))["issues"][0]["links"]
        self.assertEqual([l["host"] for l in links if l["host"] != "www.anthropic.com"], ["xn--bcher-kva.example", "exemple.org"])

    def test_mail_hors_sujet_ou_illisible_ignore(self):
        s = veille.snapshot(folder({
            "a.eml": issue("Promo exceptionnelle"), "b.eml": issue("[Veille IA] Semaine 99"), "c.eml": b"pas un mail",
            "d.eml": issue(date="n'importe quoi"), "e.txt": issue(), "gros.eml": issue(body="x" * (veille.MAX_BYTES + 1)),
        }))
        self.assertEqual(s["issues"], [])

    def test_html_pathologique_en_temps_borne(self):
        for body in ("<" * 190_000, "<a href='https://x.example/'>" * 6000, "<p>" * 60_000):
            t = time.monotonic()
            veille.snapshot(folder({"a.eml": issue(body=body)}))
            self.assertLess(time.monotonic() - t, 2.0)

    def test_dossier_absent_config_et_nom(self):
        self.assertEqual(veille.snapshot(Path(tempfile.mkdtemp()) / "nope"), {"configured": False, "issues": []})
        cfg = Path(tempfile.mkdtemp()) / "v.json"
        cfg.write_text('{"dir": "D:/x"}', encoding="utf-8")
        self.assertEqual(veille.veille_dir(cfg), Path("D:/x"))
        self.assertEqual(veille.veille_dir(cfg.with_name("absent.json")), veille.DEFAULT_DIR)
        self.assertEqual(veille.name({"kind": "actus", "year": 2026, "week": 4}), "veille-actus-2026-04.eml")


class VeilleRouteTest(ServerBase):
    def test_authentification_exigee_lecture_journalisee(self):
        self.assertEqual(self.call("GET", "/api/veille")[0], 401)
        _, token = self.enroll()
        with mock.patch("jarvis.server.veille_snapshot", return_value={"configured": True, "issues": []}):
            status, body, _ = self.call("GET", "/api/veille", token=token)
        self.assertEqual((status, body), (200, {"configured": True, "issues": []}))
        self.assertIn("veille_read", str(self.call("GET", "/api/audit?limit=20", token=token)[1]))


if __name__ == "__main__":
    unittest.main()
