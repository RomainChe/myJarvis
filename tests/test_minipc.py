"""Tuile Mini-PC : lecture des mesures, problèmes du doctor sans chemin personnel, route authentifiée."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import minipc
from tests.test_server import ServerBase

APT_OUT = """Reading package lists...
Inst libssl3 [3.0.1] (3.0.2 Debian-Security:12/stable-security [amd64])
Inst vim [9.0] (9.1 Debian:12.5/stable [amd64])
Conf vim (9.1 Debian:12.5/stable [amd64])
"""
MEMINFO = "MemTotal:       1000 kB\nMemFree:         100 kB\nMemAvailable:    250 kB\n"


class Mesures(unittest.TestCase):
    def setUp(self):
        minipc._cache.clear()

    def test_apt_compte_les_paquets_et_ceux_de_securite(self):
        self.assertEqual(minipc.parse_apt(APT_OUT), {"count": 2, "security": 1})
        self.assertEqual(minipc.parse_apt(""), {"count": 0, "security": 0})

    def test_ram(self):
        self.assertEqual(minipc.ram_pct(MEMINFO), 75)
        self.assertIsNone(minipc.ram_pct("n'importe quoi"))

    def test_derniere_relance_recente_seulement(self):
        state = Path(tempfile.mkdtemp()) / "w.json"
        self.assertIsNone(minipc._restart_at(state))
        state.write_text(json.dumps({"restart": 1000}), encoding="utf-8")
        self.assertEqual(minipc._restart_at(state, now=lambda: 2000), 1000)
        self.assertIsNone(minipc._restart_at(state, now=lambda: 1000 + minipc.RESTART_SHOWN_S + 1))
        state.write_text(json.dumps({"restart": "x"}), encoding="utf-8")
        self.assertIsNone(minipc._restart_at(state, now=lambda: 2000))

    def test_mesure_en_panne_donne_none_sans_exception(self):
        def boom():
            raise OSError("capteur")
        self.assertIsNone(minipc._memo("t", 60, boom))

    def test_statut_problemes_sans_chemin_personnel(self):
        home = str(Path.home())
        rep = [("core", None), ("sauvegarde", f"aucune sauvegarde dans {home}/backups")]
        with mock.patch.object(minipc.doctor, "report", return_value=rep), mock.patch.object(minipc, "_restart_at", return_value=None):
            s = minipc.status(None, 8765, Path(tempfile.mkdtemp()))
        self.assertEqual(s["problems"], [{"name": "sauvegarde", "problem": "aucune sauvegarde dans ~/backups"}])
        self.assertIsNone(s["backup_age_h"])
        self.assertGreater(s["disk_total_gb"], 0)


class Route(ServerBase):
    def test_authentification_exigee(self):
        self.assertEqual(self.call("GET", "/api/minipc")[0], 401)
        _, token = self.enroll()
        with mock.patch.object(minipc, "status", return_value={"problems": []}):
            status, body, _ = self.call("GET", "/api/minipc", token=token)
        self.assertEqual((status, body), (200, {"problems": []}))


if __name__ == "__main__":
    unittest.main()
