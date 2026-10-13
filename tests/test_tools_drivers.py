import sys
import unittest

if sys.platform != "win32":  # outils PC Windows : testés sur le PC principal seulement
    raise unittest.SkipTest("outils PC Windows")

import os
import tempfile
from pathlib import Path
from unittest import mock

from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.pc import drivers
from pcbase import PcBase, yes


class DriverwatchTest(PcBase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "driverwatch").mkdir()
        (Path(tmp.name) / "driverwatch" / "__main__.py").touch()
        self.dir = tmp.name
        mock.patch.dict(os.environ, {"JARVIS_DRIVERWATCH_DIR": tmp.name}).start()
        self.popen = mock.patch.object(drivers.subprocess, "Popen").start()
        self.addCleanup(mock.patch.stopall)

    def test_niveaux(self):
        self.assertEqual(REGISTRY["driverwatch_accept"].level, Level.N1)
        self.assertTrue(REGISTRY["driverwatch_accept"].taint_blocked)
        self.assertEqual(REGISTRY["driverwatch_update_all"].level, Level.N2)

    def test_accept(self):
        self.assertEqual(self.run_tool("driverwatch_accept"), {"driverwatch": "accepté"})
        self.assertEqual(self.popen.call_args.args[0][1:], ["-m", "driverwatch", "accept"])
        self.assertEqual(self.popen.call_args.kwargs["cwd"], Path(self.dir))

    def test_update_all_confirme(self):
        self.assertEqual(self.run_tool("driverwatch_update_all", confirm=yes), {"driverwatch": "mise à jour lancée"})
        self.assertEqual(self.popen.call_args.args[0][1:], ["-m", "driverwatch", "update-all"])

    def test_update_all_sans_confirmation(self):
        self.assert_refused_without_confirmation("driverwatch_update_all", {})
        self.popen.assert_not_called()

    def test_driverwatch_introuvable(self):
        with mock.patch.dict(os.environ, {"JARVIS_DRIVERWATCH_DIR": self.dir + "-absent"}):
            with self.assertRaises(FileNotFoundError):
                self.run_tool("driverwatch_accept")
        self.popen.assert_not_called()

    def test_entree_invalide(self):
        with self.assertRaises(ValueError):
            self.run_tool("driverwatch_accept", {"x": 1})

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("driverwatch_accept", {})

    def test_regles_du_routeur(self):
        router = Router()
        for text in ("accepte la mise à jour des pilotes", "Jarvis, valide la mise à jour", "oui, vas-y mets à jour",
                     "ok lance la mise à jour des drivers"):
            self.assertEqual(router.route(text), ("driverwatch_accept", {}), text)
        self.assertIsNone(router.route("mets à jour tous les pilotes"))  # N2 : jamais par le routeur (S12/C4)


if __name__ == "__main__":
    unittest.main()
