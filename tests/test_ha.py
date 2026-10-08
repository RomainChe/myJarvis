import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from jarvis.core import ha

SEEN = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        SEEN.append((self.command, self.path, self.headers.get("Authorization"), None))
        if self.headers.get("Authorization") != "Bearer tok":
            return self._send(401)
        if self.path == "/api/config":
            return self._send(200, b'{"version": "2026.1.0"}')
        if self.path == "/api/states/light.salon":
            return self._send(200, b'{"state": "on"}')
        if self.path == "/redir":
            return self._send(302, headers=[("Location", "http://127.0.0.1:1/")])
        self._send(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append((self.command, self.path, self.headers.get("Authorization"), body))
        self._send(200, b"[]")


class TestHA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        SEEN.clear()
        self.patches = [mock.patch.object(ha, "URL", self.url),
                        mock.patch.object(ha, "get_secret", return_value="tok")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_nominal(self):
        self.assertEqual(ha.version(), "2026.1.0")
        self.assertEqual(ha.state("light.salon")["state"], "on")
        ha.call_service("light", "turn_on", "light.salon", brightness=100)
        self.assertEqual(SEEN[-1][1:], ("/api/services/light/turn_on", "Bearer tok",
                                        {"brightness": 100, "entity_id": "light.salon"}))

    def test_entrees_invalides_sans_requete(self):
        for bad in ("../config", "light.salon/../x", "all", "Light.Salon", "light.a,light.b"):
            with self.assertRaises(ValueError):
                ha.state(bad)
        with self.assertRaises(ValueError):
            ha.call_service("light", "turn_on", "all")
        with self.assertRaises(ValueError):
            ha.call_service("../x", "turn_on", "light.salon")
        self.assertEqual(SEEN, [])

    def test_token_refuse_absent_et_injoignable_sans_fuite(self):
        with mock.patch.object(ha, "get_secret", return_value="mauvais"):
            with self.assertRaises(ha.HAError) as c:
                ha.version()
        self.assertNotIn("mauvais", str(c.exception))
        with mock.patch.object(ha, "get_secret", return_value=None):
            with self.assertRaises(ha.HAError):
                ha.version()
        with mock.patch.object(ha, "URL", "http://127.0.0.1:1"):
            with self.assertRaises(ha.HAError):
                ha.version()

    def test_redirection_non_suivie(self):
        with self.assertRaises(ha.HAError):
            ha._request("GET", "/redir")

    def test_identifiants_dans_l_url_et_coffre_indisponible(self):
        with mock.patch.object(ha, "URL", "http://user:pw@127.0.0.1"):
            with self.assertRaises(ha.HAError):
                ha.version()
        with mock.patch.object(ha, "get_secret", side_effect=ha.keyring.errors.KeyringError("verrouillé")):
            with self.assertRaises(ha.HAError):
                ha.version()

    def test_schema_refuse(self):
        with mock.patch.object(ha, "URL", "file:///etc/passwd"):
            with self.assertRaises(ha.HAError):
                ha.version()


if __name__ == "__main__":
    unittest.main()
