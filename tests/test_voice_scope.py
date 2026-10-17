"""Lot 4c : clé de portée « voix » (n'ouvre que POST /api/voice) et migration du schéma des appareils."""
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis import __main__ as cli
from jarvis.core import voice as voice_mod
from jarvis.core.audit import Audit
from jarvis.core.devices import Devices
from test_server import ServerBase


class ScopeRouteTest(ServerBase):
    def voice_key(self):
        return self.devices.add_scoped("voix-salon", "voice")[1]

    def test_cle_voix_ouvre_api_voice(self):
        with mock.patch.object(voice_mod, "execute", return_value="ok"):
            status, body, _ = self.call("POST", "/api/voice", {"text": "allume la télé", "client": "salon"}, token=self.voice_key())
        self.assertEqual((status, body), (200, {"answer": "ok"}))

    def test_cle_voix_refusee_partout_ailleurs(self):
        token = self.voice_key()
        for method, path, body in (("GET", "/api/ping", None), ("GET", "/api/devices", None), ("GET", "/api/audit", None),
                                   ("POST", "/api/chat", {"text": "allume la télé"})):
            status, answer, _ = self.call(method, path, body, token=token)
            self.assertEqual((status, answer), (403, {"detail": "portée insuffisante"}), path)
        self.assertEqual(self.audit.db.execute("SELECT count(*) FROM audit WHERE tool='scope' AND decision='refusé'").fetchone()[0], 1)

    def test_cle_voix_refusee_ne_compte_pas_comme_echec_d_auth(self):
        token = self.voice_key()
        for _ in range(30):
            self.call("GET", "/api/ping", token=token)
        _, other = self.enroll()
        self.assertEqual(self.call("GET", "/api/ping", token=other)[0], 200)

    def test_cle_complete_garde_l_acces_a_tout(self):
        _, token = self.enroll()
        self.assertEqual(self.call("GET", "/api/ping", token=token)[0], 200)
        with mock.patch.object(voice_mod, "execute", return_value="ok"):
            self.assertEqual(self.call("POST", "/api/voice", {"text": "allume la télé"}, token=token)[0], 200)

    def test_cle_voix_revoquee_ou_inconnue_donne_401(self):
        dev_id, token = self.devices.add_scoped("v", "voice")
        self.assertTrue(self.devices.revoke(dev_id))
        self.assertEqual(self.call("POST", "/api/voice", {"text": "a"}, token=token)[0], 401)
        self.assertEqual(self.call("POST", "/api/voice", {"text": "a"}, token=None)[0], 401)


class ScopeStorageTest(unittest.TestCase):
    def test_portee_et_nom_invalides(self):
        d = Devices(":memory:")
        for name, scope in (("", "voice"), ("x" * 41, "voice"), ("ok", "root"), ("ok", "")):
            with self.assertRaises(ValueError):
                d.add_scoped(name, scope)

    def test_migration_garde_les_appareils_existants_en_acces_complet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "d.db")
            old = sqlite3.connect(path)  # schéma d'avant le lot 4c : pas de colonne scope
            old.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, "
                        "created REAL NOT NULL, last_used REAL, revoked INTEGER NOT NULL DEFAULT 0)")
            token = "ancien-token"
            old.execute("INSERT INTO devices (name, token_hash, created) VALUES ('tel', ?, ?)",
                        (__import__("hashlib").sha256(token.encode()).hexdigest(), __import__("time").time()))
            old.commit()
            old.close()
            for _ in range(2):  # relançable : la seconde ouverture ne refait pas l'ALTER
                d = Devices(path)
                self.assertEqual(d.check_scoped(token)[2], "full")
                d.db.close()


class ScopeCliTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(cli, "Devices", side_effect=lambda path: self.devices)
        self.devices, self.audit = Devices(":memory:"), Audit(":memory:")
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, argv, tty=True):
        with mock.patch("sys.stdin.isatty", return_value=tty), mock.patch("builtins.print") as out:
            code = cli.device_or_serve(argv, self.audit)
        return code, str(out.call_args_list)

    def test_add_voice_cree_une_cle_de_portee_voix(self):
        code, out = self.run_cli(["device", "add", "--voice", "voix-salon"])
        self.assertEqual(code, 0)
        token = re.search(r": ([A-Za-z0-9_-]{20,})", out).group(1)
        self.assertEqual(self.devices.check_scoped(token)[1:], ("voix-salon", "voice"))
        self.assertEqual(self.audit.db.execute("SELECT count(*) FROM audit WHERE tool='device_add'").fetchone()[0], 1)

    def test_add_voice_exige_un_terminal_et_un_nom_valide(self):
        self.assertEqual(self.run_cli(["device", "add", "--voice", "x"], tty=False)[0], 1)
        self.assertEqual(self.run_cli(["device", "add", "--voice", ""])[0], 2)
        self.assertEqual(self.run_cli(["device", "add", "--autre", "x"])[0], 2)
        self.assertEqual(self.devices.db.execute("SELECT count(*) FROM devices").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
