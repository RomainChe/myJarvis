"""Bouton micro de la PWA : actif par défaut, coupé librement, réarmé sous conditions, tout journalisé."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core.mic import Mic
from tests.test_server import ServerBase


class FakeSpeaker:
    def ignore_until(self):
        return 0


class MicWebTest(ServerBase):
    def setUp(self):
        self.flag = Path(tempfile.mkdtemp()) / "mic_off"
        self.mic = Mic(lambda audio: None, speaker=FakeSpeaker(), flag=self.flag)
        super().setUp()
        self.token = self.enroll()

    def enroll(self, name="téléphone"):
        code = self.devices.new_code()
        return self.call("POST", "/api/enroll", {"code": code, "name": name})[1]["token"]

    def rows(self):
        return [r for r in self.audit.last(10) if r[2] == "mic_switch"]

    def test_actif_par_defaut_puis_coupe_et_journal(self):
        state = self.call("GET", "/api/mic", token=self.token)[1]
        self.assertEqual((state["on"], state["strong"]), (True, False))
        status, body, _ = self.call("POST", "/api/mic", {"on": False}, token=self.token)
        self.assertEqual((status, body), (200, {"on": False}))
        self.assertTrue(self.flag.exists())
        self.assertEqual(self.call("GET", "/api/mic", token=self.token)[1]["on"], False)
        self.assertEqual(self.rows()[0][5], "auto")

    def test_rearmer_sans_cle_d_acces_est_libre(self):
        self.mic.disable()
        self.assertEqual(self.call("POST", "/api/mic", {"on": True}, token=self.token)[0], 200)
        self.assertFalse(self.flag.exists())

    def test_rearmer_avec_cle_d_acces_exige_la_signature(self):
        self.mic.disable()
        with mock.patch("jarvis.server.Passkeys.has", return_value=True):
            status, _, _ = self.call("POST", "/api/mic", {"on": True}, token=self.token)
        self.assertEqual(status, 403)
        self.assertTrue(self.flag.exists())  # toujours coupé
        self.assertEqual(self.rows()[0][5], "refusé")

    def test_journal_en_echec_ne_rearme_pas(self):
        self.mic.disable()
        with mock.patch.object(type(self.audit), "log", side_effect=OSError):
            self.assertEqual(self.call("POST", "/api/mic", {"on": True}, token=self.token)[0], 500)
        self.assertTrue(self.flag.exists())

    def test_entree_invalide_et_sans_authentification(self):
        self.assertEqual(self.call("POST", "/api/mic", {"on": "oui"}, token=self.token)[0], 422)
        self.assertEqual(self.call("POST", "/api/mic", {"on": False})[0], 401)
        self.assertEqual(self.call("GET", "/api/mic")[0], 401)
        self.assertFalse(self.flag.exists())


class MicAbsentTest(ServerBase):
    def test_sans_micro_le_bouton_se_cache(self):
        _, token = self.enroll()
        self.assertEqual(self.call("GET", "/api/mic", token=token)[1]["available"], False)
        self.assertEqual(self.call("POST", "/api/mic", {"on": True}, token=token)[0], 404)


if __name__ == "__main__":
    unittest.main()
