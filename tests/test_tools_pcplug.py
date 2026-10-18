import math
import threading
import unittest
from unittest import mock

from jarvis.core import ha
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.home import pcplug
from pcbase import PcBase, no, yes

from jarvis.core.host import load_pc_tools

load_pc_tools()  # outils PC réels (Windows) ou proxys de l'agent (Linux) : `power` doit exister


class PcPlugOnTest(PcBase):
    def setUp(self):
        super().setUp()
        self.state = mock.patch.object(ha, "state", return_value={"state": "off"}).start()
        self.call = mock.patch.object(ha, "call_service").start()
        self.addCleanup(mock.patch.stopall)

    def test_niveau(self):
        self.assertEqual(REGISTRY["pc_plug_on"].level, Level.N1)

    def test_nominal(self):
        self.assertEqual(self.run_tool("pc_plug_on"), {"prise": "on"})
        self.call.assert_called_once_with("switch", "turn_on", "switch.prise_pc")

    def test_prise_injoignable(self):
        self.state.return_value = {"state": "unavailable"}
        with self.assertRaises(ha.HAError):
            self.run_tool("pc_plug_on")
        self.call.assert_not_called()

    def test_entree_invalide(self):
        with self.assertRaises(ValueError):
            self.run_tool("pc_plug_on", {"delay": 1})
        self.call.assert_not_called()

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("pc_plug_on", {})

    def test_regle_du_routeur(self):
        import jarvis.tools.assist, jarvis.tools.dev, jarvis.tools.mail  # noqa: F401,E401
        from jarvis.core.router import Router
        router = Router()
        for text in ("allume la prise du PC", "Jarvis, rallume le PC", "allume mon pc principal",
                     "rallume la prise PC", "Jarvis, rallume la prise pc."):
            self.assertEqual(router.route(text), ("pc_plug_on", {}), text)
        self.assertIsNone(router.route("allume la prise"))  # une seule prise aujourd'hui, mais pas d'ambiguïté plus tard


class PcOffPlugTest(PcBase):
    def setUp(self):
        super().setUp()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(pcplug, "HAS_PC_TOOLS", False).start()  # Core du mini-PC
        self.watts = mock.patch.object(pcplug, "watts", return_value=80.0).start()
        self.state = mock.patch.object(ha, "state", return_value={"state": "on"}).start()
        self.call = mock.patch.object(ha, "call_service").start()
        self.power = mock.Mock(return_value={"power": "shutdown"})
        real = REGISTRY["power"]
        import dataclasses
        from jarvis.core.tools import _registry
        mock.patch.dict(_registry, {"power": dataclasses.replace(real, run=self.power)}).start()
        self.threads = mock.patch.object(pcplug.threading, "Thread").start()

    def test_niveau(self):
        self.assertEqual(REGISTRY["pc_off_plug"].level, Level.N2)

    def test_nominal_arret_puis_cycle_en_fond(self):
        result = self.run_tool("pc_off_plug", confirm=yes)
        self.assertEqual(result, {"power": "shutdown", "prise": "coupure planifiée"})
        self.power.assert_called_once_with(action="shutdown")
        self.threads.assert_called_once()
        self.call.assert_not_called()  # la coupure vient plus tard, jamais dans l'appel

    def test_core_sur_le_pc_refuse(self):
        with mock.patch.object(pcplug, "HAS_PC_TOOLS", True):
            with self.assertRaises(RuntimeError):
                self.run_tool("pc_off_plug", confirm=yes)
        self.power.assert_not_called()

    def test_prise_injoignable_rien_lance(self):
        self.state.return_value = {"state": "unavailable"}
        with self.assertRaises(ha.HAError):
            self.run_tool("pc_off_plug", confirm=yes)
        self.power.assert_not_called()

    def test_mesure_illisible_rien_lance(self):
        self.watts.return_value = math.inf
        with self.assertRaises(ha.HAError):
            self.run_tool("pc_off_plug", confirm=yes)
        self.power.assert_not_called()

    def test_arret_en_echec_pas_de_cycle(self):
        self.power.side_effect = RuntimeError("PC injoignable")
        with self.assertRaises(RuntimeError):
            self.run_tool("pc_off_plug", confirm=yes)
        self.threads.assert_not_called()

    def test_deja_en_cours(self):
        with pcplug._busy:
            with self.assertRaises(RuntimeError):
                self.run_tool("pc_off_plug", confirm=yes)
        self.power.assert_not_called()

    def test_sans_confirmation(self):
        self.assert_refused_without_confirmation("pc_off_plug", {})

    def test_entree_invalide(self):
        with self.assertRaises(ValueError):
            self.run_tool("pc_off_plug", {"delay": 1}, confirm=yes)
        self.power.assert_not_called()

    def test_permission_power_relevee_refusee(self):
        with mock.patch.object(pcplug, "effective", side_effect=lambda t: 3 if t.name == "power" else 2):
            with self.assertRaises(ValueError):
                self.run_tool("pc_off_plug", confirm=yes)
        self.power.assert_not_called()


class CutWhenOffTest(unittest.TestCase):
    """Le cycle d'attente, sans réseau ni horloge réelle."""

    def run_cycle(self, readings, clock_step=1.0):
        t = [0.0]
        now = lambda: t[0]  # noqa: E731
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            t[0] += s * clock_step
        seq = iter(readings)
        with mock.patch.object(pcplug, "watts", side_effect=lambda: next(seq, readings[-1])),              mock.patch.object(ha, "call_service") as call:
            return pcplug.cut_when_off(sleep=sleep, now=now), call, sleeps

    def test_coupe_apres_chute_et_revérification(self):
        out, call, sleeps = self.run_cycle([80, 60, 2, 2])
        self.assertEqual(out, "prise coupée")
        call.assert_called_once_with("switch", "turn_off", "switch.prise_pc")
        self.assertEqual(sleeps, [5, 5, 30])

    def test_puissance_remontee_pendant_les_30s(self):
        out, call, _ = self.run_cycle([80, 2, 40])
        self.assertIn("remontée", out)
        call.assert_not_called()

    def test_delai_depasse_ne_coupe_pas(self):
        out, call, _ = self.run_cycle([80])
        self.assertIn("délai", out)
        call.assert_not_called()

    def test_seuil_reglable_et_borne(self):
        with mock.patch.dict("os.environ", {"JARVIS_PC_IDLE_W": "3"}):
            self.assertEqual(pcplug.limit_w(), 5.0)
        with mock.patch.dict("os.environ", {"JARVIS_PC_IDLE_W": "abc"}):
            self.assertEqual(pcplug.limit_w(), 10.0)


if __name__ == "__main__":
    unittest.main()
