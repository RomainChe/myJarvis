"""Étape 1 de la Phase 3 : appareils, enrôlement et serveur local (vrai uvicorn sur 127.0.0.1, client http.client)."""
import http.client
import json
import re
import socket
import threading
import time
import unittest
from unittest import mock

from jarvis import __main__ as cli
from jarvis import server
from jarvis.core import devices as dev
from jarvis.core.audit import Audit
from jarvis.core.chat import Chat
from jarvis.core.devices import Devices


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerBase(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.devices, self.audit = Devices(":memory:"), Audit(":memory:")
        self.chat = Chat(self.audit)
        self.srv = server.make_server(self.devices, self.audit, self.port, self.chat)
        threading.Thread(target=self.srv.run, daemon=True).start()
        for _ in range(100):
            if self.srv.started:
                break
            time.sleep(0.05)
        self.assertTrue(self.srv.started)
        self.addCleanup(self.stop)

    def stop(self):
        self.srv.should_exit = True
        time.sleep(0.3)

    def call(self, method, path, body=None, token=None, **headers):
        h = {"Host": f"127.0.0.1:{self.port}", "Origin": f"http://127.0.0.1:{self.port}"}
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if token:
            h["Authorization"] = f"Bearer {token}"
        h.update({k.replace("_", "-"): v for k, v in headers.items()})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=data, headers={k: v for k, v in h.items() if v is not None})
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, (json.loads(raw) if raw else None), r

    def enroll(self, name="téléphone"):
        code = self.devices.new_code()
        status, body, _ = self.call("POST", "/api/enroll", {"code": code, "name": name})
        self.assertEqual(status, 200)
        return body["id"], body["token"]


class AuthTest(ServerBase):
    def test_enrolement_puis_ping(self):
        _, token = self.enroll()
        status, body, _ = self.call("GET", "/api/ping", token=token)
        self.assertEqual((status, body), (200, {"ok": True, "device": "téléphone"}))

    def test_token_absent_malforme_inconnu_ou_revoque_donne_401(self):
        device_id, token = self.enroll()
        for headers in ({}, {"Authorization": "Bearer"}, {"Authorization": "Basic " + token},
                        {"Authorization": "Bearer " + "x" * 500}, {"Authorization": "Bearer inconnu"}):
            status, body, _ = self.call("GET", "/api/ping", **headers)
            self.assertEqual((status, body), (401, {"detail": "non autorisé"}), headers)
        self.assertTrue(self.devices.revoke(device_id))  # effet immédiat, vérifié en base à chaque requête
        self.assertEqual(self.call("GET", "/api/ping", token=token)[0], 401)

    def test_code_a_usage_unique_et_expiration(self):
        code = self.devices.new_code()
        self.assertEqual(self.call("POST", "/api/enroll", {"code": code, "name": "a"})[0], 200)
        self.assertEqual(self.call("POST", "/api/enroll", {"code": code, "name": "b"})[0], 401)  # rejeu
        code = self.devices.new_code()
        with mock.patch.object(dev, "_now", return_value=time.time() + dev.CODE_TTL_S + 1):
            self.assertEqual(self.call("POST", "/api/enroll", {"code": code, "name": "c"})[0], 401)

    def test_echecs_d_enrolement_brulent_les_codes_et_verrouillent(self):
        good = self.devices.new_code()
        bodies = set()
        for _ in range(dev.MAX_FAILS):
            status, body, _ = self.call("POST", "/api/enroll", {"code": "faux", "name": "x"})
            self.assertEqual(status, 401)
            bodies.add(json.dumps(body))
        self.assertEqual(len(bodies), 1)  # faux, expiré et déjà utilisé disent la même chose
        self.assertEqual(self.call("POST", "/api/enroll", {"code": good, "name": "x"})[0], 401)  # brûlé et verrouillé

    def test_trop_d_echecs_d_authentification_donnent_429(self):
        for _ in range(server.AUTH_FAIL_MAX):
            self.assertEqual(self.call("GET", "/api/ping", token="faux")[0], 401)
        status, _, r = self.call("GET", "/api/ping", token="faux")
        self.assertEqual(status, 429)
        self.assertTrue(r.getheader("Retry-After"))

    def test_audit_sans_token(self):
        _, token = self.enroll("tel")
        self.call("GET", "/api/ping", token="SECRET-INCONNU")
        rows = str(self.audit.last(10))
        self.assertIn("pwa:1", rows)
        self.assertIn("token invalide", rows)
        self.assertNotIn("SECRET-INCONNU", rows)
        self.assertNotIn(token, rows)
        self.assertTrue(self.audit.verify())

    def test_token_stocke_sous_forme_de_hash(self):
        _, token = self.enroll()
        stored = self.devices.db.execute("SELECT token_hash FROM devices").fetchone()[0]
        self.assertNotEqual(stored, token)
        self.assertEqual(len(stored), 64)


class GuardTest(ServerBase):
    def test_host_etranger_refuse(self):  # DNS rebinding
        _, token = self.enroll()
        for host in ("evil.example", f"localhost:{self.port}", "127.0.0.1", f"127.0.0.1:{self.port + 1}"):
            self.assertEqual(self.call("GET", "/api/ping", token=token, Host=host)[0], 400, host)

    def test_origin_obligatoire_sur_les_ecritures(self):
        code = self.devices.new_code()
        body = {"code": code, "name": "x"}
        for origin in (None, "http://evil.example", f"https://127.0.0.1:{self.port}"):
            self.assertEqual(self.call("POST", "/api/enroll", body, Origin=origin)[0], 403, origin)
        self.assertEqual(self.call("POST", "/api/enroll", body)[0], 200)  # le code n'a pas été consommé avant

    def test_type_taille_et_longueur(self):
        self.assertEqual(self.call("POST", "/api/enroll", b"{}", Content_Type="text/plain")[0], 415)
        self.assertEqual(self.call("POST", "/api/enroll", b"x" * (server.BODY_MAX + 1))[0], 413)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)  # corps en morceaux, sans Content-Length
        conn.request("POST", "/api/enroll", body=iter([b"{}"]), encode_chunked=True, headers={
            "Host": f"127.0.0.1:{self.port}", "Origin": f"http://127.0.0.1:{self.port}",
            "Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 411)
        conn.close()

    def test_validation_ne_renvoie_pas_l_entree(self):
        status, body, _ = self.call("POST", "/api/enroll", {"code": "SECRET-CODE" * 20, "name": "n"})
        self.assertEqual((status, body), (422, {"detail": "requête invalide"}))
        status, body, _ = self.call("POST", "/api/enroll", {"code": 12345, "name": ["x"]})
        self.assertEqual(status, 422)
        self.assertNotIn("12345", json.dumps(body))

    def test_en_tetes_de_securite_partout(self):
        for status, _, r in (self.call("GET", "/api/ping"), self.call("GET", "/inconnu"),
                             self.call("GET", "/api/ping", Host="evil.example")):
            for key in ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy"):
                self.assertTrue(r.getheader(key), (status, key))
            self.assertEqual(r.getheader("Cache-Control"), "no-store")
            self.assertNotIn("unsafe-inline", r.getheader("Content-Security-Policy"))
            self.assertIsNone(r.getheader("Server"))
            self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))  # pas de CORS

    def test_pas_de_documentation_publique(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_transfer_encoding_avec_content_length_refuse(self):  # constat 1 : 2 Mo passaient avec CL: 10 + chunked
        crlf = "\r\n"
        head = crlf.join([f"POST /api/enroll HTTP/1.1", f"Host: 127.0.0.1:{self.port}",
                          f"Origin: http://127.0.0.1:{self.port}", "Content-Type: application/json",
                          "Content-Length: 10", "Transfer-Encoding: chunked", "", ""])
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as c:
            c.sendall(head.encode())
            c.sendall(b"200000\r\n" + b"x" * 0x200000 + b"\r\n0\r\n\r\n")
            self.assertIn(b" 411 ", c.recv(200).split(b"\r\n")[0])

    def test_get_sans_authorization_ne_bloque_personne(self):  # constat 2 : DoS par une page web
        _, token = self.enroll()
        for _ in range(server.AUTH_FAIL_MAX * 3):
            self.assertEqual(self.call("GET", "/api/ping")[0], 401)
        self.assertEqual(self.call("GET", "/api/ping", token=token)[0], 200)
        self.assertEqual(self.audit.last(1)[0][1], "pwa:1")  # aucune ligne d'audit ajoutée par ces GET

    def test_token_valide_jamais_bloque_par_le_compteur(self):
        _, token = self.enroll()
        for _ in range(server.AUTH_FAIL_MAX + 2):
            self.call("GET", "/api/ping", token="faux")
        self.assertEqual(self.call("GET", "/api/ping", token="faux")[0], 429)
        self.assertEqual(self.call("GET", "/api/ping", token=token)[0], 200)

    def test_verrouillage_d_enrolement_n_ecrit_plus_dans_l_audit(self):  # constat 3
        for _ in range(dev.MAX_FAILS):
            self.call("POST", "/api/enroll", {"code": "faux", "name": "x"})
        lines = len(self.audit.last(1000))
        for _ in range(20):
            self.assertEqual(self.call("POST", "/api/enroll", {"code": "faux", "name": "x"})[0], 401)
        self.assertEqual(len(self.audit.last(1000)), lines)

    def test_port_non_numerique_donne_un_message(self):  # constat 6
        with mock.patch.dict("os.environ", {"JARVIS_PORT": "abc"}), mock.patch("builtins.print") as out:
            self.assertEqual(cli.device_or_serve(["serve"], Audit(":memory:")), 2)
        self.assertIn("JARVIS_PORT", str(out.call_args_list))

    def test_ecoute_uniquement_sur_loopback(self):
        hosts = {s.getsockname()[0] for srv in self.srv.servers for s in srv.sockets}
        self.assertEqual(hosts, {"127.0.0.1"})

    def test_hote_non_configurable(self):
        self.assertEqual(server.HOST, "127.0.0.1")
        with mock.patch.dict("os.environ", {"JARVIS_PORT": "80"}):
            with self.assertRaises(ValueError):
                server.port_from_env()


class DevicesTest(unittest.TestCase):
    def test_nom_invalide_et_liste(self):
        d = Devices(":memory:")
        for bad in ("", "  ", "x" * 41, "a\nb"):
            with self.assertRaises(ValueError):
                d.enroll(d.new_code(), bad)
        d.enroll(d.new_code(), " tel ")
        self.assertEqual(d.list()[0][1], "tel")

    def test_deux_enrolements_simultanes_un_seul_gagne(self):
        d = Devices(":memory:")
        code, results = d.new_code(), []
        threads = [threading.Thread(target=lambda: results.append(d.enroll(code, "x"))) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(r is not None for r in results), 1)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.db = ":memory:"
        p = mock.patch.object(cli, "Devices", side_effect=lambda path: self.devices)
        self.devices, self.audit = Devices(":memory:"), Audit(":memory:")
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, argv, tty):
        with mock.patch("sys.stdin.isatty", return_value=tty), mock.patch("builtins.print") as out:
            code = cli.device_or_serve(argv, self.audit)
        return code, str(out.call_args_list)

    def test_add_et_revoke_exigent_un_terminal(self):
        self.assertEqual(self.run_cli(["device", "add"], tty=False)[0], 1)
        self.assertEqual(self.run_cli(["device", "revoke", "1"], tty=False)[0], 1)
        self.assertEqual(self.devices.db.execute("SELECT COUNT(*) FROM enroll_codes").fetchone()[0], 0)

    def test_add_revoke_list_et_audit(self):
        code, out = self.run_cli(["device", "add"], tty=True)
        self.assertEqual(code, 0)
        self.assertIn("usage unique", out)
        token = self.devices.enroll(re.search(r": ([A-Za-z0-9_-]{20,})", out).group(1), "pc")[1]
        self.assertEqual(self.run_cli(["device", "list"], tty=False)[0], 0)
        self.assertEqual(self.run_cli(["device", "revoke", "1"], tty=True)[0], 0)
        self.assertIsNone(self.devices.check(token))
        self.assertEqual(self.run_cli(["device", "revoke", "1"], tty=True)[0], 1)
        rows = str(self.audit.last(10))
        self.assertIn("device_add", rows)
        self.assertIn("device_revoke", rows)
        self.assertNotIn(token, rows)

    def test_usage_invalide(self):
        for argv in (["device"], ["device", "revoke", "abc"], ["device", "add", "extra"]):
            self.assertEqual(self.run_cli(argv, tty=True)[0], 2, argv)


if __name__ == "__main__":
    unittest.main()
