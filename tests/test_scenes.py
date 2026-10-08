import dataclasses
import unittest
from unittest import mock

from jarvis.core import ha
from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level, _registry
from jarvis.tools.home import scenes, tv
from pcbase import PcBase


class CinemaTest(PcBase):
    def setUp(self):
        super().setUp()
        self.clock = 0.0
        self.state = {"state": "off", "app": None}
        self.calls = []
        patches = [mock.patch.object(tv, "tv_status", side_effect=lambda: dict(self.state)),
                   mock.patch.object(tv, "tv_on", side_effect=lambda: self.calls.append("on")),
                   mock.patch.object(tv, "tv_open_app", side_effect=lambda a: self.calls.append(a)),
                   mock.patch.object(scenes, "_sleep", side_effect=self.tick),
                   mock.patch.object(scenes, "_now", side_effect=lambda: self.clock)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tick(self, seconds):
        self.clock += seconds

    def test_attente_bornee_en_temps_reel(self):
        tv.tv_status.side_effect = lambda: (self.tick(4), dict(self.state))[1]  # HA lent : 4 s par lecture
        self.run_tool("scene_cinema", {"app": ""})
        self.assertLess(self.clock, scenes.WAIT_S + 4 + 1 + 4)  # une seule échéance, pas 15 itérations x 4 s

    def test_ha_qui_tombe_pendant_l_attente_donne_non_confirmee(self):
        calls = iter([dict(self.state)])  # première lecture ok, puis HA injoignable
        def status():
            try:
                return next(calls)
            except StopIteration:
                raise ha.HAError("Home Assistant injoignable") from None
        tv.tv_status.side_effect = status
        self.assertEqual(self.run_tool("scene_cinema", {"app": ""})["tv"], "non confirmée")

    def test_erreur_ha_visible_dans_le_resultat(self):
        self.state = {"state": "on", "app": "accueil"}
        with mock.patch.object(tv, "tv_open_app", side_effect=ha.HAError("action refusée pour l'utilisateur jarvis")):
            out = self.run_tool("scene_cinema", {"app": "youtube"})
        self.assertEqual((out["app"], out["erreur"]), ("non confirmée", "action refusée pour l'utilisateur jarvis"))
        self.assertNotIn("erreur", self.run_tool("scene_cinema", {"app": ""}))

    def test_sous_outil_releve_refuse_toute_la_scene(self):
        for sub_tool, app in (("tv_on", ""), ("tv_open_app", "youtube")):
            raised = dataclasses.replace(REGISTRY[sub_tool], level=Level.N2)
            with mock.patch.dict(_registry, {sub_tool: raised}):
                with self.assertRaises(ValueError):
                    self.run_tool("scene_cinema", {"app": app})
            self.assertEqual(self.calls, [], sub_tool)

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
