import sys
import unittest

if sys.platform != "win32":  # outils PC Windows : testés sur le PC principal seulement
    raise unittest.SkipTest("outils PC Windows")

from unittest import mock

from jarvis.core import ha
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.home import pcplug
from jarvis.tools.pc import session
from pcbase import PcBase, no, yes


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
        from jarvis.core.router import Router
        router = Router()
        for text in ("allume la prise du PC", "Jarvis, rallume le PC", "allume mon pc principal"):
            self.assertEqual(router.route(text), ("pc_plug_on", {}), text)
        self.assertIsNone(router.route("allume la prise"))  # une seule prise aujourd'hui, mais pas d'ambiguïté plus tard


class PcOffPlugTest(PcBase):
    def setUp(self):
        super().setUp()
        self.state = mock.patch.object(ha, "state", return_value={"state": "on"}).start()
        self.call = mock.patch.object(ha, "call_service").start()
        self.power = mock.patch.object(session, "power").start()
        self.addCleanup(mock.patch.stopall)

    def test_niveau(self):
        self.assertEqual(REGISTRY["pc_off_plug"].level, Level.N2)

    def test_nominal_script_puis_arret(self):
        order = mock.Mock()
        order.attach_mock(self.call, "script")
        order.attach_mock(self.power, "power")
        result = self.run_tool("pc_off_plug", confirm=yes)
        self.assertEqual(result["power"], "shutdown")
        self.assertEqual([c[0] for c in order.mock_calls], ["script", "power"])  # le script attend avant l'arrêt
        self.call.assert_called_once_with("script", "turn_on", "script.pc_prise_off")
        self.power.assert_called_once_with("shutdown")

    def test_prise_injoignable_rien_lance(self):
        self.state.return_value = {"state": "unavailable"}
        with self.assertRaises(ha.HAError):
            self.run_tool("pc_off_plug", confirm=yes)
        self.call.assert_not_called()
        self.power.assert_not_called()

    def test_script_en_echec_pas_d_arret(self):
        self.call.side_effect = ha.HAError("HA injoignable")
        with self.assertRaises(ha.HAError):
            self.run_tool("pc_off_plug", confirm=yes)
        self.power.assert_not_called()

    def test_sans_confirmation(self):
        self.assert_refused_without_confirmation("pc_off_plug", {})

    def test_entree_invalide(self):
        with self.assertRaises(ValueError):
            self.run_tool("pc_off_plug", {"delay": 1}, confirm=yes)
        self.power.assert_not_called()


if __name__ == "__main__":
    unittest.main()
