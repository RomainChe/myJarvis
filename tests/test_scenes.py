import unittest
from unittest import mock

from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.home import scenes, tv
from pcbase import PcBase


class CinemaTest(PcBase):
    def setUp(self):
        super().setUp()
        self.state = {"state": "off", "app": None}
        self.calls = []
        patches = [mock.patch.object(tv, "tv_status", side_effect=lambda: dict(self.state)),
                   mock.patch.object(tv, "tv_on", side_effect=lambda: self.calls.append("on")),
                   mock.patch.object(tv, "tv_open_app", side_effect=lambda a: self.calls.append(a)),
                   mock.patch.object(scenes, "_sleep")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_niveau(self):
        self.assertEqual(REGISTRY["scene_cinema"].level, Level.N1)
        self.assertTrue(REGISTRY["scene_cinema"].taint_blocked)

    def test_tv_eteinte_puis_appli_verifiees(self):
        def on():
            self.calls.append("on")
            self.state = {"state": "on", "app": "accueil"}

        def open_app(a):
            self.calls.append(a)
            self.state = {"state": "on", "app": a}
        tv.tv_on.side_effect, tv.tv_open_app.side_effect = on, open_app
        out = self.run_tool("scene_cinema", {"app": " Netflix "})
        self.assertEqual(self.calls, ["on", "netflix"])
        self.assertEqual((out["tv"], out["app"]), ("allumée", "netflix"))
        self.assertIn("volets du salon", out["non_traité"])  # on ne prétend pas avoir fait ce qui n'existe pas

    def test_tv_deja_allumee_et_sans_appli(self):
        self.state = {"state": "on", "app": "accueil"}
        out = self.run_tool("scene_cinema", {"app": ""})
        self.assertEqual(self.calls, [])
        self.assertEqual((out["tv"], out["app"]), ("allumée", None))

    def test_tv_qui_ne_s_allume_pas_n_ouvre_pas_d_appli(self):
        out = self.run_tool("scene_cinema", {"app": "youtube"})
        self.assertEqual(self.calls, ["on"])
        self.assertEqual((out["tv"], out["app"]), ("non confirmée", None))

    def test_appli_non_confirmee(self):
        self.state = {"state": "on", "app": "accueil"}
        out = self.run_tool("scene_cinema", {"app": "youtube"})
        self.assertEqual(out["app"], "non confirmée")

    def test_appli_inconnue_refusee_avant_toute_action(self):
        with self.assertRaises(ValueError):
            self.run_tool("scene_cinema", {"app": "com.evil.app"})
        self.assertEqual(self.calls, [])

    def test_niveau_releve_bloque(self):
        self.assert_refused_if_level_raised("scene_cinema", {"app": ""})


class CinemaIntentsTest(unittest.TestCase):
    def test_routage(self):
        r = Router()
        self.assertEqual(r.route("mets le mode cinéma"), ("scene_cinema", {"app": ""}))
        self.assertEqual(r.route("Jarvis, lance le mode cinema sur Netflix"), ("scene_cinema", {"app": "Netflix"}))
        for text in ("mode cinéma sur com.evil.app", "éteins le mode cinéma", "mets le mode nuit"):
            self.assertIsNone(r.route(text), text)


if __name__ == "__main__":
    unittest.main()
