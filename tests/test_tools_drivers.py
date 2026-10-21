import sys
import unittest

if sys.platform != "win32":  # outils PC Windows : testés sur le PC principal seulement
    raise unittest.SkipTest("outils PC Windows")

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.pc import drivers
from pcbase import PcBase, yes


class DriverwatchBase(PcBase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "driverwatch").mkdir()
        (Path(tmp.name) / "driverwatch" / "__main__.py").touch()
        self.dir = tmp.name
        mock.patch.dict(os.environ, {"JARVIS_DRIVERWATCH_DIR": tmp.name}).start()
        self.popen = mock.patch.object(drivers.subprocess, "Popen").start()
        mock.patch.dict(drivers._updating, {"on": False}).start()
        self.addCleanup(mock.patch.stopall)


class DriverwatchTest(DriverwatchBase):
    def test_niveaux(self):
        self.assertEqual(REGISTRY["driverwatch_accept"].level, Level.N1)
        self.assertTrue(REGISTRY["driverwatch_accept"].taint_blocked)
        self.assertEqual(REGISTRY["driverwatch_update_all"].level, Level.N2)

    def test_accept(self):
        self.assertEqual(self.run_tool("driverwatch_accept"), {"driverwatch": "accepté"})
        self.assertEqual(self.popen.call_args.args[0][1:], ["-m", "driverwatch", "accept"])
        self.assertEqual(self.popen.call_args.kwargs["cwd"], Path(self.dir))

    def test_update_all_confirme(self):
        mock.patch.object(drivers.threading, "Thread").start()
        self.assertEqual(self.run_tool("driverwatch_update_all", confirm=yes), {"driverwatch": "mise à jour lancée"})
        self.assertEqual(self.popen.call_args.args[0][1:], ["-m", "driverwatch", "update-all"])

    def test_update_all_relance_une_verification_a_la_fin(self):
        thread = mock.patch.object(drivers.threading, "Thread").start()
        self.run_tool("driverwatch_update_all", confirm=yes)
        self.assertTrue(drivers._updating["on"])  # l'onglet continue de relire tant que ça dure
        proc, spawn = mock.Mock(), mock.Mock()
        drivers._recheck_after(proc, spawn)
        proc.wait.assert_called_once()
        spawn.assert_called_once_with("check")
        self.assertFalse(drivers._updating["on"])
        self.assertIs(thread.call_args.kwargs["target"], drivers._recheck_after)

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


NOW = datetime(2026, 10, 20, 12, 0).timestamp()


class PcDriversTest(DriverwatchBase):
    def setUp(self):
        super().setUp()
        self.status = Path(self.dir) / "status.json"
        self.spawn = mock.Mock()
        mock.patch.dict(drivers._tried, {"at": 0.0}).start()

    def write(self, at="2026-10-20T09:00:00", rows=None):
        self.status.write_text(json.dumps({"at": at, "drivers": rows if rows is not None else [
            {"id": "oem20.inf", "name": "Wi-Fi", "status": "ok", "days": 0},
            {"id": "oem51.inf", "name": "RTX" * 100, "status": "moderate", "days": 203, "newer": True, "installed": "595.97"},
            {"id": "x", "status": "<img>"}, "pas un dict"]}), encoding="utf-8")

    def snap(self, now=NOW):
        return drivers.status(self.status, now, self.spawn)

    def test_niveau_n0_reserve_au_proprietaire(self):
        self.assertEqual(REGISTRY["pc_drivers"].level, Level.N0)
        self.assertTrue(REGISTRY["pc_drivers"].owner_only)

    def test_releve_valide_trie_et_borne(self):
        self.write()
        s = self.snap()
        self.assertEqual((s["at"], s["checking"], s["started"]), ("2026-10-20T09:00", False, False))
        self.assertEqual([d["id"] for d in s["drivers"]], ["oem51.inf", "oem20.inf"])  # retard en tête, statut inconnu écarté
        self.assertEqual(len(s["drivers"][0]["name"]), 120)
        self.assertIsNone(s["drivers"][1]["latest"])
        self.spawn.assert_not_called()

    def test_releve_absent_ou_perime_relance_une_fois_par_heure(self):
        s = self.snap()
        self.assertEqual((s["at"], s["checking"], s["started"]), (None, True, True))
        self.spawn.assert_called_once_with("check")
        self.assertFalse(self.snap(NOW + 60)["started"])  # pas de deuxième lancement dans l'heure
        self.write(at="2026-10-18T09:00:00")
        self.assertTrue(self.snap(NOW + 3700)["started"])
        self.assertEqual(self.spawn.call_count, 2)

    def test_fichier_illisible_ou_trop_gros(self):
        for text in ("{pas du json", json.dumps({"at": "hier", "drivers": []}), "x" * (drivers.MAX_BYTES + 1), "[" * 60000):
            self.status.write_text(text, encoding="utf-8")
            self.assertIsNone(drivers._read(self.status), text[:20])

    def test_lancement_impossible(self):
        self.spawn.side_effect = OSError
        s = self.snap()
        self.assertEqual((s["checking"], s["started"]), (False, False))

    def test_projet_absent(self):
        with mock.patch.dict(os.environ, {"JARVIS_DRIVERWATCH_DIR": self.dir + "-absent"}):
            self.assertFalse(self.snap()["configured"])
        self.spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
