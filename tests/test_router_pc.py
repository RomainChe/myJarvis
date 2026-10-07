"""Intentions des outils PC N1 : phrases simples reconnues sans LLM."""
import unittest

from jarvis.core.router import Router


class PcIntentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = Router()

    def check(self, expected, *texts):
        for text in texts:
            self.assertEqual(self.router.route(text), expected, text)

    def test_volume(self):
        self.check(("set_volume", {"level": 30}), "mets le volume à 30", "Jarvis, mets le volume à 30%",
                   "règle le son sur 30 pour cent", "volume à 30")

    def test_volume_invalide_part_au_llm(self):
        for text in ("mets le volume à fort", "mets le volume à -5", "mets le volume à 3.5", "mets le volume à trente",
                     "mets le volume à ٣٠"):
            self.assertIsNone(self.router.route(text), text)

    def test_sourdine(self):
        self.check(("mute", {"muted": True}), "coupe le son", "Jarvis, coupe le son !", "mets en sourdine")
        self.check(("mute", {"muted": False}), "remets le son", "réactive le son", "désactive la sourdine")

    def test_media(self):
        self.check(("media_control", {"action": "play_pause"}), "pause", "mets pause", "mets la pause", "Jarvis, lecture")
        self.check(("media_control", {"action": "next"}), "suivant", "morceau suivant", "passe au morceau suivant")
        self.check(("media_control", {"action": "previous"}), "précédent", "piste précédente", "reviens au précédent")

    def test_phrases_proches_non_routees(self):
        for text in ("coupe le chauffage", "coupe le son de la télé", "mets la musique de Noël", "pause café"):
            self.assertIsNone(self.router.route(text), text)


if __name__ == "__main__":
    unittest.main()
