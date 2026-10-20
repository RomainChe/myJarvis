"""Étape (c) de l'interface TV : clé de portée « tv » (GET /api/tv et POST /api/voice, rien d'autre)."""
import re
import unittest
from unittest import mock

from jarvis import __main__ as cli
from jarvis import server
from jarvis.core import voice as voice_mod
from jarvis.core.audit import Audit
from jarvis.core.devices import Devices
from test_server import ServerBase

SNAPSHOT = {"location": "Lille", "network": {"ms": 9}, "system": {"cpu": 1}, "uptime_s": 5,
            "weather": {"temp_c": 14.0, "sky": "Dégagé", "min_c": 9.0, "max_c": 17.0, "wind_kmh": 12.0, "alerts": ["gel"]}}


class TvRouteTest(ServerBase):
    def setUp(self):
        super().setUp()
        for target, value in ((server.Dashboard, "snapshot"), (server.reminders, "pending")):
            p = mock.patch.object(target, value, return_value=SNAPSHOT if value == "snapshot" else [(1, 5.0, "pain", "rappel")])
            p.start()
            self.addCleanup(p.stop)
        self.token = self.devices.add_scoped("tv-salon", "tv")[1]

    def test_cle_tv_lit_l_ecran_sans_rien_d_autre(self):
        status, body, _ = self.call("GET", "/api/tv", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"reminders": 1, "weather": {"temp_c": 14.0, "sky": "Dégagé", "min_c": 9.0, "max_c": 17.0}})
        self.assertNotIn("Lille", str(body))  # ni ville, ni système, ni vent, ni texte des rappels : la TV est vue par des invités

    def test_meteo_absente_donne_none(self):
        with mock.patch.object(server.Dashboard, "snapshot", return_value={"location": None, "weather": None}):
            self.assertIsNone(self.call("GET", "/api/tv", token=self.token)[1]["weather"])

    def test_cle_tv_ouvre_api_voice(self):
        with mock.patch.object(voice_mod, "execute", return_value="ok"):
            status, body, _ = self.call("POST", "/api/voice", {"text": "allume la télé", "client": "tv"}, token=self.token)
        self.assertEqual((status, body), (200, {"answer": "ok"}))

    def test_post_voice_exige_l_origine_du_core(self):
        # Revue Sécurité : l'APK doit envoyer Origin (CoreLink) ; le Core ne l'assouplit pas, même pour une clé tv valide.
        with mock.patch.object(voice_mod, "execute", return_value="ok"):
            status, body, _ = self.call("POST", "/api/voice", {"text": "allume la télé"}, token=self.token, Origin="https://autre.ts.net")
        self.assertEqual((status, body), (403, {"detail": "origine refusée"}))

    def test_cle_tv_refusee_partout_ailleurs(self):
        for method, path, body in (("GET", "/api/ping", None), ("GET", "/api/dashboard", None), ("GET", "/api/audit", None),
                                   ("GET", "/api/reminders", None), ("POST", "/api/chat", {"text": "allume la télé"})):
            status, answer, _ = self.call(method, path, body, token=self.token)
            self.assertEqual((status, answer), (403, {"detail": "portée insuffisante"}), path)

    def test_cle_voix_et_inconnue_refusees_sur_api_tv(self):
        voice = self.devices.add_scoped("voix-salon", "voice")[1]
        self.assertEqual(self.call("GET", "/api/tv", token=voice)[0], 403)
        self.assertEqual(self.call("GET", "/api/tv", token="inconnue")[0], 401)
        self.assertEqual(self.call("GET", "/api/tv")[0], 401)

    def test_cle_complete_lit_aussi_api_tv(self):
        _, full = self.enroll()
        self.assertEqual(self.call("GET", "/api/tv", token=full)[0], 200)

    def test_cle_tv_revoquee_donne_401(self):
        dev_id, token = self.devices.add_scoped("tv-2", "tv")
        self.assertTrue(self.devices.revoke(dev_id))
        self.assertEqual(self.call("GET", "/api/tv", token=token)[0], 401)

    def test_lecture_journalisee(self):
        self.call("GET", "/api/tv", token=self.token)
        self.assertEqual(self.audit.db.execute("SELECT count(*) FROM audit WHERE tool='tv_read'").fetchone()[0], 1)


class TvCliTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(cli, "Devices", side_effect=lambda path: self.devices)
        self.devices, self.audit = Devices(":memory:"), Audit(":memory:")
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, argv, tty=True):
        with mock.patch("sys.stdin.isatty", return_value=tty), mock.patch("builtins.print") as out:
            code = cli.device_or_serve(argv, self.audit)
        return code, str(out.call_args_list)

    def test_add_tv_cree_une_cle_de_portee_tv(self):
        code, out = self.run_cli(["device", "add", "--tv", "tv-salon"])
        self.assertEqual(code, 0)
        token = re.search(r": ([A-Za-z0-9_-]{20,})", out).group(1)
        self.assertEqual(self.devices.check_scoped(token)[1:], ("tv-salon", "tv"))
        self.assertEqual(self.audit.db.execute("SELECT count(*) FROM audit WHERE tool='device_add'").fetchone()[0], 1)

    def test_add_tv_exige_un_terminal_et_un_nom_valide(self):
        self.assertEqual(self.run_cli(["device", "add", "--tv", "x"], tty=False)[0], 1)
        self.assertEqual(self.run_cli(["device", "add", "--tv", ""])[0], 2)
        self.assertEqual(self.devices.db.execute("SELECT count(*) FROM devices").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
