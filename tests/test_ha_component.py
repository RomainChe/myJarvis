"""Lot 4c : partie sans Home Assistant du composant jarvis_voice (requête vers le Core, lecture de la réponse)."""
import importlib.util
import json
import unittest
from pathlib import Path

PATH = Path(__file__).parents[1] / "deploy/homeassistant/custom_components/jarvis_voice/core.py"
spec = importlib.util.spec_from_file_location("jarvis_voice_core", PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class BuildRequestTest(unittest.TestCase):
    def test_nominal(self):
        url, headers, body = core.build_request("http://127.0.0.1:8765/", "cle", "salon", "allume le PC")
        self.assertEqual(url, "http://127.0.0.1:8765/api/voice")
        self.assertEqual(headers["Origin"], "http://127.0.0.1:8765")  # le Core refuse un POST sans Origin
        self.assertEqual(headers["Authorization"], "Bearer cle")
        self.assertEqual(json.loads(body), {"text": "allume le PC", "client": "salon"})

    def test_https_tailnet_accepte(self):
        self.assertEqual(core.build_request("https://core.tailnet.ts.net", "k", "salon", "x")[0],
                         "https://core.tailnet.ts.net/api/voice")

    def test_reglages_invalides_refuses(self):
        for url, key, client in (("http://192.168.1.5:8765", "k", "salon"),      # http hors boucle locale : la clé fuirait en clair
                                 ("http://127.0.0.1.evil.com", "k", "salon"), ("http://user@127.0.0.1:8765", "k", "salon"),
                                 ("http://127.0.0.1:8765/autre", "k", "salon"), ("ftp://127.0.0.1", "k", "salon"),
                                 ("http://127.0.0.1:8765", "", "salon"), ("http://127.0.0.1:8765", "k", "../x"),
                                 ("http://127.0.0.1:8765", "k", "")):
            with self.assertRaises(ValueError, msg=(url, key, client)):
                core.build_request(url, key, client, "x")


class ParseAnswerTest(unittest.TestCase):
    def test_reponses(self):
        self.assertEqual(core.parse_answer(b'{"answer": "C\'est fait."}', 100), "C'est fait.")
        self.assertEqual(core.parse_answer('{"answer": ""}', 100), "")  # Core hors ligne : rien à lire
        for bad in (b"", b"pas du json", b'{"x": 1}', b'{"answer": 5}', b'{"answer": "' + b"a" * 200 + b'"}', b"[]"):
            self.assertIsNone(core.parse_answer(bad, 100), bad)


if __name__ == "__main__":
    unittest.main()
