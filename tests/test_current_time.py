"""current_time : phrase heure + date, niveau N0, routée sans LLM."""
import unittest
from datetime import datetime
from unittest import mock

import jarvis.__main__  # noqa: F401  (enregistre tous les outils)
from jarvis.core import reminders
from jarvis.core.host import load_pc_tools
from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools import assist

load_pc_tools()  # le routeur valide son catalogue contre les outils PC


class CurrentTime(unittest.TestCase):
    def test_niveau_n0(self):
        self.assertEqual(REGISTRY["current_time"].level, Level.N0)

    def test_phrase(self):
        ts = datetime(2026, 10, 17, 9, 5).timestamp()
        with mock.patch.object(reminders, "now", return_value=ts):
            self.assertEqual(assist.current_time(), "Il est 9 h 05, samedi 17 octobre 2026.")

    def test_routage(self):
        router = Router()
        for phrase in ("Jarvis, quelle heure est-il ?", "quel jour sommes-nous", "c'est quoi l'heure"):
            self.assertEqual(router.route(phrase), ("current_time", {}), phrase)


if __name__ == "__main__":
    unittest.main()
