import subprocess
import unittest
from unittest import mock

from jarvis.core.permissions import Refused
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.pc import session
from pcbase import PcBase, no, yes


class SessionBase(PcBase):
    """Aucune action réelle : chaque test remplace le backend système ET subprocess.run."""

    def setUp(self):
        super().setUp()
        for target in ("_screen_off", "_lock", "_suspend"):
            patcher = mock.patch.object(session, target)
            setattr(self, target.strip("_"), patcher.start())
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(session.subprocess, "run")
        self.shutdown = patcher.start()
        self.addCleanup(patcher.stop)


class ScreenOffTest(SessionBase):
    def test_niveau(self):
        self.assertEqual(REGISTRY["screen_off"].level, Level.N1)

    def test_nominal(self):
        self.assertEqual(self.run_tool("screen_off"), {"screen": "off"})
        self.screen_off.assert_called_once_with()

    def test_entree_invalide(self):
        with self.assertRaises(ValueError):
            self.run_tool("screen_off", {"delay": 1})
        self.screen_off.assert_not_called()

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("screen_off", {})


class LockSessionTest(SessionBase):
    def test_niveau(self):
        self.assertEqual(REGISTRY["lock_session"].level, Level.N1)

    def test_nominal(self):
        self.assertEqual(self.run_tool("lock_session"), {"locked": True})
        self.lock.assert_called_once_with()

    def test_echec_journalise(self):
        self.lock.side_effect = OSError("verrouillage impossible")
        with self.assertRaises(OSError):
            self.run_tool("lock_session")
        self.assertTrue(self.audit.last(1)[0][6].startswith("erreur"))

    def test_entree_invalide(self):
        with self.assertRaises(ValueError):
            self.run_tool("lock_session", {"force": True})
        self.lock.assert_not_called()

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("lock_session", {})


class PowerTest(SessionBase):
    def test_niveau(self):
        self.assertEqual(REGISTRY["power"].level, Level.N2)
        self.assertIn("Home Assistant", REGISTRY["power"].description)

    def test_veille_apres_confirmation(self):
        self.assertEqual(self.run_tool("power", {"action": "sleep"}, confirm=yes), {"power": "sleep"})
        self.suspend.assert_called_once_with()
        self.shutdown.assert_not_called()

    def test_arret_et_redemarrage_liste_d_arguments_avec_delai(self):
        for action, flag in (("shutdown", "/s"), ("restart", "/r")):
            self.run_tool("power", {"action": action}, confirm=yes)
            cmd, kwargs = self.shutdown.call_args.args[0], self.shutdown.call_args.kwargs
            self.assertEqual(cmd, [str(session.SHUTDOWN), flag, "/t", str(session.GRACE_S)])
            self.assertNotIn("shell", kwargs)
        self.assertNotIn("/f", cmd)
        self.suspend.assert_not_called()

    def test_entree_invalide(self):
        for bad in ({"action": "hibernate"}, {"action": "Shutdown"}, {"action": "sleep /f"}, {"action": ""},
                    {"action": 1}, {}):
            with self.assertRaises(ValueError, msg=bad):
                self.run_tool("power", bad, confirm=yes)
        self.suspend.assert_not_called()
        self.shutdown.assert_not_called()

    def test_sans_confirmation_rien_ne_part(self):
        for action in session.POWER_ACTIONS:
            with self.assertRaises(Refused):
                self.run_tool("power", {"action": action}, confirm=no)
        self.suspend.assert_not_called()
        self.shutdown.assert_not_called()
        self.assertEqual(self.audit.last(1)[0][5], "refusé")

    def test_echec_de_shutdown_journalise(self):
        self.shutdown.side_effect = subprocess.CalledProcessError(1, "shutdown")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_tool("power", {"action": "shutdown"}, confirm=yes)
        self.assertTrue(self.audit.last(1)[0][6].startswith("erreur"))


class PowerCancelTest(SessionBase):
    def test_niveau(self):
        self.assertEqual(REGISTRY["power_cancel"].level, Level.N1)

    def test_nominal_annule_l_arret(self):
        self.shutdown.return_value = subprocess.CompletedProcess([], 0)
        self.assertEqual(self.run_tool("power_cancel"), {"power": "cancelled"})
        self.assertEqual(self.shutdown.call_args.args[0], [str(session.SHUTDOWN), "/a"])

    def test_rien_a_annuler_n_est_pas_une_erreur(self):
        self.shutdown.return_value = subprocess.CompletedProcess([], 1116)
        self.assertEqual(self.run_tool("power_cancel"), {"power": "nothing_pending"})

    def test_autre_echec_leve_une_erreur(self):
        self.shutdown.return_value = subprocess.CompletedProcess([], 5)
        with self.assertRaises(OSError):
            self.run_tool("power_cancel")

    def test_entree_invalide(self):
        for bad in ({"action": "x"}, {"force": True}):
            with self.assertRaises(ValueError):
                self.run_tool("power_cancel", bad)
        self.shutdown.assert_not_called()

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("power_cancel", {})


if __name__ == "__main__":
    unittest.main()
