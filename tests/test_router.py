import json
import tempfile
import time
import unittest
from pathlib import Path

import jarvis.tools.pc  # noqa: F401  (enregistre les outils)
from jarvis.core.router import CATALOGUE, Router, normalize
from jarvis.core.tools import REGISTRY


class RouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = Router()

    def test_normalisation(self):
        self.assertEqual(normalize("Jarvis, ÉTAT du Système ?"), "etat du systeme")
        self.assertEqual(normalize("  !! "), "")

    def test_phrase_exacte_et_approchee(self):
        self.assertEqual(self.router.route("Jarvis, état du système"), ("system_status", {}))
        self.assertEqual(self.router.route("etat du sytème"), ("system_status", {}))  # faute de frappe
        self.assertEqual(self.router.route("liste les processus !"), ("list_processes", {}))

    def test_slots_et_defauts(self):
        self.assertEqual(self.router.route("Cherche le fichier rapport.pdf"),
                         ("search_files", {"name": "rapport.pdf", "folder": "~"}))
        self.assertEqual(self.router.route("trouve facture dans mes documents"),
                         ("search_files", {"name": "facture", "folder": "documents"}))

    def test_inconnu_ou_vide_renvoie_none(self):
        for text in ("", "   ", "Jarvis", "raconte-moi une blague sur les pirates", "ouvre"):
            self.assertIsNone(self.router.route(text), text)

    def test_catalogue_ne_cible_que_des_outils_enregistres(self):
        for intent in json.loads(CATALOGUE.read_text(encoding="utf-8")):
            self.assertIn(intent["tool"], REGISTRY)

    def test_catalogue_personnalise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "intents.json")
            path.write_text('[{"tool": "x", "patterns": ["volume {n}"]}]', encoding="utf-8")
            self.assertEqual(Router(path).route("Volume 30"), ("x", {"n": "30"}))

    def test_latence_moins_de_50_ms(self):
        texts = ["état du système", "cherche le fichier rapport", "phrase totalement inconnue du routeur"]
        start = time.perf_counter()
        for _ in range(100):
            for text in texts:
                self.router.route(text)
        per_call_ms = (time.perf_counter() - start) * 1000 / (100 * len(texts))
        self.assertLess(per_call_ms, 50)


if __name__ == "__main__":
    unittest.main()
