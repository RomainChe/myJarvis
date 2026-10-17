"""Lot 4b : POST /api/voice (Core) et client voix du PC (réseau et audio simulés)."""
import io
import json
import unittest
from unittest import mock

from jarvis import voice_client
from jarvis.core import voice as voice_mod
from test_server import ServerBase

URL = "https://core.tailnet.ts.net"


class VoiceRouteTest(ServerBase):
    def test_nominal_source_voix_et_client_journalises(self):
        _, token = self.enroll()
        with mock.patch.object(voice_mod, "execute", return_value="ok") as ex:
            status, body, _ = self.call("POST", "/api/voice", {"text": "allume la télé", "client": "salon"}, token=token)
        self.assertEqual((status, body), (200, {"answer": "ok"}))
        self.assertEqual(ex.call_args.kwargs["source"], "voix")
        rows = self.audit.db.execute("SELECT source, args FROM audit WHERE tool='chat'").fetchall()
        self.assertEqual(rows[0][0], "voix")
        self.assertIn("1/salon", rows[0][1])

    def test_sans_cle_ou_cle_inconnue_refuse(self):
        for token in (None, "inconnu"):
            with mock.patch.object(voice_mod, "execute") as ex:
                status, _, _ = self.call("POST", "/api/voice", {"text": "allume la télé"}, token=token)
            self.assertEqual(status, 401)
            ex.assert_not_called()

    def test_entree_invalide(self):
        _, token = self.enroll()
        for bad in ({}, {"text": ""}, {"text": "x" * 5000}, {"text": "a", "client": "../x"}, {"text": 5}):
            self.assertEqual(self.call("POST", "/api/voice", bad, token=token)[0], 422, bad)

    def test_n2_refuse_rien_execute(self):
        _, token = self.enroll()
        with mock.patch.object(voice_mod, "ask", return_value="x"):
            status, body, _ = self.call("POST", "/api/voice", {"text": "vide la corbeille"}, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(self.audit.db.execute("SELECT count(*) FROM audit WHERE decision='confirmé'").fetchone()[0], 0)

    def test_limite_de_debit(self):
        _, token = self.enroll()
        with mock.patch.object(voice_mod, "execute", return_value="ok"):
            codes = [self.call("POST", "/api/voice", {"text": "allume la télé"}, token=token)[0]
                     for _ in range(server_voice_max() + 1)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(set(codes[:-1]), {200})


def server_voice_max():
    from jarvis import server
    return server.VOICE_MAX


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ClientTest(unittest.TestCase):
    def remote(self, urlopen):
        return voice_client.RemoteVoice(URL, "cle-de-test", "pc", urlopen=urlopen)

    def test_nominal_envoie_texte_cle_et_client(self):
        seen = {}

        def urlopen(req, timeout):
            seen.update(url=req.full_url, auth=req.get_header("Authorization"), origin=req.get_header("Origin"),
                        body=json.loads(req.data))
            return FakeResp(b'{"answer": "Fait."}')
        self.assertEqual(self.remote(urlopen).handle("allume la lumière"), "Fait.")
        self.assertEqual(seen["url"], URL + "/api/voice")
        self.assertEqual(seen["auth"], "Bearer cle-de-test")
        self.assertEqual(seen["origin"], URL)
        self.assertEqual(seen["body"], {"text": "allume la lumière", "client": "pc"})

    def test_texte_vide_invalide(self):
        with self.assertRaises(ValueError):
            self.remote(mock.Mock()).handle("  ")

    def test_core_injoignable_ou_refus_message_fixe(self):
        import urllib.error
        for exc in (urllib.error.URLError("x"), urllib.error.HTTPError(URL, 401, "non", {}, None), TimeoutError()):
            self.assertEqual(self.remote(mock.Mock(side_effect=exc)).handle("salut"), voice_client.UNREACHABLE_MSG)
        self.assertEqual(self.remote(lambda r, timeout: FakeResp(b"pas du json")).handle("salut"), voice_client.UNREACHABLE_MSG)
        self.assertEqual(self.remote(lambda r, timeout: FakeResp(b'{"answer": 5}')).handle("salut"), voice_client.UNREACHABLE_MSG)

    def test_url_https_exigee_et_hote_de_confiance(self):
        for bad in ("", "http://100.64.0.5:443", "https://exemple.com", "https://core.ts.net/x"):
            with mock.patch.dict("os.environ", {voice_client.URL_ENV: bad}), self.assertRaises(ValueError, msg=bad):
                voice_client.core_url()
        with mock.patch.dict("os.environ", {voice_client.URL_ENV: URL}):
            self.assertEqual(voice_client.core_url(), URL)

    def test_identifiant_de_client(self):
        with mock.patch.dict("os.environ", {voice_client.CLIENT_ENV: "Salon 2"}), self.assertRaises(ValueError):
            voice_client.client_id()

    def test_cle_absente_refuse_de_demarrer(self):
        with mock.patch.dict("os.environ", {voice_client.URL_ENV: URL}), \
                mock.patch.object(voice_client, "get_secret", return_value=None):
            self.assertEqual(voice_client.run(mock.Mock()), 2)


if __name__ == "__main__":
    unittest.main()


class ReminderSpeechTest(unittest.TestCase):
    def announce(self, call):
        from jarvis import __main__ as cli
        got = {}
        with mock.patch.object(cli.reminders, "briefing_time", return_value=None), \
                mock.patch.object(cli.reminders, "run", lambda fn, at: got.update(fn=fn)), \
                mock.patch("jarvis.core.doctor.notify_all"), \
                mock.patch("jarvis.core.agentlink.agent_url", return_value="http://100.64.0.2:8788"), \
                mock.patch("jarvis.core.agentlink.call", call):
            cli._reminders(mock.Mock(), None)  # Core du mini-PC : pas de micro local
            return got["fn"]("timer", "pâtes", 0)

    def test_le_core_demande_la_lecture_a_l_agent(self):
        call = mock.Mock(return_value={"say": "ok"})
        self.assertEqual(self.announce(call), "voix + push")
        self.assertEqual(call.call_args.args[:2], ("run", "say"))
        self.assertIn("pâtes", call.call_args.args[2]["text"])

    def test_pc_eteint_push_seul(self):
        from jarvis.core.agentlink import AgentError
        self.assertEqual(self.announce(mock.Mock(side_effect=AgentError("x"))), "push")


class StartMicTest(unittest.TestCase):
    def test_core_sans_outils_pc_demarre_sans_micro(self):
        from jarvis import __main__ as cli
        with mock.patch("jarvis.core.host.HAS_PC_TOOLS", False):
            self.assertIsNone(cli.start_mic(mock.Mock()))
