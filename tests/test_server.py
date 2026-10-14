"""Étape 1 de la Phase 3 : appareils, enrôlement et serveur local (vrai uvicorn sur 127.0.0.1, client http.client)."""
import http.client
import json
import re
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
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
    mic = None  # remplacé par les tests du bouton micro

    def setUp(self):
        self.port = free_port()
        self.devices, self.audit = Devices(":memory:"), Audit(":memory:")
        self.chat = Chat(self.audit)
        self.web = Path(tempfile.mkdtemp())
        for name, text in (("index.html", "<h1>JARVIS</h1>"), ("app.js", "export {}"), ("app.css", "body{}"),
                           ("sw.js", "//"), ("notes.txt", "secret"), ("manifest.webmanifest", "{}")):
            (self.web / name).write_text(text)
        (self.web / "sub").mkdir()
        (self.web / "sub" / "x.js").write_text("export {}")
        self.srv = server.make_server(self.devices, self.audit, self.port, self.chat, self.web, mic=self.mic)
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
        is_json = "json" in (r.getheader("Content-Type") or "") and not r.getheader("Content-Type", "").startswith("application/manifest")
        return r.status, (json.loads(raw) if raw and is_json else raw or None), r

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

    def test_quota_par_appareil_borne_le_journal(self):
        _, token = self.enroll("tel")
        before = len(self.audit.last(10 ** 6))
        statuses = [self.call("GET", "/api/ping", token=token)[0] for _ in range(server.QUOTA_MAX + 50)]
        self.assertEqual(statuses.count(200), server.QUOTA_MAX)
        self.assertEqual(set(statuses[server.QUOTA_MAX:]), {429})
        self.assertEqual(len(self.audit.last(10 ** 6)) - before, 1)  # une seule ligne « quota » pour 50 refus
        self.assertTrue(self.audit.verify())

    def test_audit_health_signale_un_journal_trop_gros(self):
        self.assertEqual(self.audit.health(), [])
        self.audit.log("cli", "x", {}, None, "auto", None)
        with mock.patch("jarvis.core.audit.ROWS_ALERT", 0):
            self.assertEqual(len(self.audit.health()), 1)

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

    def test_en_tetes_supplementaires(self):
        _, _, r = self.call("GET", "/api/ping")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn("camera=()", r.getheader("Permissions-Policy"))

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
        with mock.patch.dict("os.environ", {"JARVIS_PORT": "abc"}), mock.patch.object(cli, "DB_PATH", ":memory:"),                 mock.patch("builtins.print") as out:
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


class StaticTest(ServerBase):
    def test_shell_sans_authentification_avec_les_bons_types(self):
        for path, kind in (("/", "text/html"), ("/index.html", "text/html"), ("/app.js", "text/javascript"),
                           ("/app.css", "text/css"), ("/manifest.webmanifest", "application/manifest+json")):
            status, _, r = self.call("GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(r.getheader("Content-Type").startswith(kind), path)
            self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))  # CSP aussi sur le shell

    def test_rien_d_autre_que_la_liste_de_fichiers(self):
        for path in ("/notes.txt", "/sub/x.js", "/sub", "/nope.js", "/..%2fserver.py", "/%2e%2e/server.py",
                     "/..\\server.py", "/app.js%00.txt", "//app.js", "/api", "/API/ping"):
            self.assertIn(self.call("GET", path)[0], (400, 404, 405, 307), path)
            status, body, _ = self.call("GET", path)
            self.assertNotEqual(status, 200, path)
        self.assertEqual(self.call("POST", "/", {"x": 1})[0], 405)  # lecture seule

    def test_les_routes_api_priment_sur_le_shell(self):
        self.assertEqual(self.call("GET", "/api/ping")[0], 401)  # pas du statique


class ReadRoutesTest(ServerBase):
    def test_authentification_obligatoire(self):
        for path in ("/api/audit", "/api/devices"):
            self.assertEqual(self.call("GET", path)[0], 401, path)

    def test_journal_sans_hash_ni_arguments(self):
        _, token = self.enroll("tel")
        self.audit.log("pwa:1/llm", "kill_process", {"pid": 4242, "name": "SECRET.exe"}, 2, "refusé", None)
        status, body, _ = self.call("GET", "/api/audit", token=token)
        self.assertEqual(status, 200)
        row = body["rows"][0]
        self.assertEqual(set(row), {"ts", "source", "tool", "level", "decision", "result"})
        self.assertEqual((row["source"], row["tool"], row["decision"]), ("pwa:1/llm", "kill_process", "refusé"))
        self.assertNotIn("SECRET", json.dumps(body))
        self.assertLessEqual(len(body["rows"]), server.AUDIT_ROWS)

    def test_journal_niveau_entier_et_resultat_coupe(self):
        _, token = self.enroll("tel")
        self.audit.log("pwa:1", "kill_process", {}, 2, "confirmé", "x" * 500)
        row = self.call("GET", "/api/audit", token=token)[1]["rows"][0]
        self.assertEqual(row["level"], 2)  # un entier : l'écran en fait « N2 »
        self.assertEqual(len(row["result"]), server.RESULT_MAX)

    def test_appareils_sans_hash_avec_l_appareil_courant(self):
        first, token = self.enroll("tel")
        second, _ = self.enroll("pc")
        self.devices.revoke(second)
        status, body, _ = self.call("GET", "/api/devices", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(body["current"], first)
        self.assertEqual([(d["id"], d["name"], d["revoked"]) for d in body["devices"]], [(first, "tel", False), (second, "pc", True)])
        self.assertNotIn("hash", json.dumps(body))
        self.assertNotIn(token, json.dumps(body))


TS = "pc-test.tail1234.ts.net"


class TailscaleHostTest(ServerBase):
    def setUp(self):
        super().setUp()
        self.srv.should_exit = True
        time.sleep(0.3)
        self.port = free_port()
        self.srv = server.make_server(self.devices, self.audit, self.port, self.chat, self.web, TS)
        threading.Thread(target=self.srv.run, daemon=True).start()
        for _ in range(100):
            if self.srv.started:
                break
            time.sleep(0.05)
        _, self.token = self.enroll_local()

    def enroll_local(self):
        code = self.devices.new_code()
        status, body, _ = self.call("POST", "/api/enroll", {"code": code, "name": "tel"})
        self.assertEqual(status, 200)
        return body["id"], body["token"]

    def test_nom_tailscale_avec_son_origine_https(self):
        status, body, r = self.call("GET", "/api/ping", token=self.token, Host=TS)
        self.assertEqual((status, body["ok"]), (200, True))
        self.assertIn("max-age", r.getheader("Strict-Transport-Security"))  # HSTS seulement sur le nom HTTPS
        _, _, local = self.call("GET", "/api/ping", token=self.token)
        self.assertIsNone(local.getheader("Strict-Transport-Security"))
        code = self.devices.new_code()
        ok = self.call("POST", "/api/enroll", {"code": code, "name": "x"}, Host=TS, Origin=f"https://{TS}")
        self.assertEqual(ok[0], 200)

    def test_origine_d_un_autre_host_refusee(self):  # l'Origin doit correspondre au Host utilisé, pas à « un Host permis »
        code = self.devices.new_code()
        local_origin = f"http://127.0.0.1:{self.port}"
        self.assertEqual(self.call("POST", "/api/enroll", {"code": code, "name": "x"}, Host=TS, Origin=local_origin)[0], 403)
        self.assertEqual(self.call("POST", "/api/enroll", {"code": code, "name": "x"}, Origin=f"https://{TS}")[0], 403)
        self.assertEqual(self.call("POST", "/api/enroll", {"code": code, "name": "x"}, Host=TS, Origin=f"http://{TS}")[0], 403)

    def test_autres_noms_refuses(self):
        for host in ("autre.tail1234.ts.net", f"{TS}:443", f"{TS}.evil.example", "evil.example", TS.upper(), "ts.net"):
            self.assertEqual(self.call("GET", "/api/ping", token=self.token, Host=host)[0], 400, host)


class TsHostEnvTest(unittest.TestCase):
    def check(self, value):
        with mock.patch.dict("os.environ", {"JARVIS_TS_HOST": value}):
            return server.ts_host_from_env()

    def test_valide_absent_et_invalides(self):
        self.assertEqual(self.check(TS), TS)
        self.assertIsNone(self.check(""))
        for bad in ("*.tail1234.ts.net", "pc.ts.net.evil.example", "PC.tail1234.ts.net", f"{TS}:443", f"{TS}/x",
                    "ts.net", "localhost", "127.0.0.1", "pc..tail1234.ts.net", "-pc.tail1234.ts.net", "a b.ts.net",
                    "x" * 300 + ".ts.net"):
            with self.assertRaises(ValueError, msg=bad):
                self.check(bad)


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


class TokenTest(unittest.TestCase):
    """D6 : token valable 90 jours glissants, renouvelé à chaque ouverture, ancien valable jusqu'au premier usage du nouveau."""
    def setUp(self):
        self.t = [1000.0]
        patch = mock.patch.object(dev, "_now", lambda: self.t[0])
        patch.start()
        self.addCleanup(patch.stop)
        self.d = Devices(":memory:")
        self.id, self.token = self.d.enroll(self.d.new_code(), "tel")

    def test_expire_apres_90_jours_sans_renouvellement(self):
        self.t[0] += dev.TOKEN_TTL_S - 1
        self.assertIsNotNone(self.d.check(self.token))
        self.t[0] += 2
        self.assertIsNone(self.d.check(self.token))
        self.assertIsNone(self.d.rotate(self.id, self.token))  # expiré : plus de renouvellement possible

    def test_renouvellement_prolonge_et_remplace(self):
        self.t[0] += dev.TOKEN_TTL_S - 1
        new = self.d.rotate(self.id, self.token)
        self.assertIsNotNone(self.d.check(self.token))  # réponse pas encore arrivée : l'ancien marche
        self.assertEqual(self.d.check(new), (self.id, "tel"))
        self.assertIsNone(self.d.check(self.token))  # le nouveau a servi : l'ancien est mort
        self.t[0] += dev.TOKEN_TTL_S - 1
        self.assertIsNotNone(self.d.check(new))

    def test_reponse_perdue_l_ancien_reste_valable(self):
        self.d.rotate(self.id, self.token)  # le téléphone n'a jamais reçu ce token
        newer = self.d.rotate(self.id, self.token)  # ouverture suivante, avec l'ancien
        self.assertIsNotNone(self.d.check(self.token))
        self.assertIsNotNone(self.d.check(newer))

    def test_revoque_ni_renouvele_ni_valable(self):
        self.d.revoke(self.id)
        self.assertIsNone(self.d.rotate(self.id, self.token))
        self.assertIsNone(self.d.check(self.token))

    def test_base_d_avant_d6_migree_sans_couper_les_appareils(self):
        path = str(Path(tempfile.mkdtemp()) / "old.db")
        import sqlite3
        db = sqlite3.connect(path)
        db.executescript("CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,"
                         " created REAL NOT NULL, last_used REAL, revoked INTEGER NOT NULL DEFAULT 0);")
        db.execute("INSERT INTO devices (name, token_hash, created) VALUES ('tel', ?, 0)", (dev._h("ancien"),))
        db.commit()
        db.close()
        self.assertEqual(Devices(path).check("ancien")[1], "tel")
        self.t[0] += dev.TOKEN_TTL_S + 1
        self.assertIsNone(Devices(path).check("ancien"))

    def test_revoquer_tout_sauf_un(self):
        other = self.d.enroll(self.d.new_code(), "pc")[1]
        self.assertEqual(self.d.revoke_all(keep=self.id), 1)
        self.assertIsNotNone(self.d.check(self.token))
        self.assertIsNone(self.d.check(other))
        self.assertEqual(self.d.revoke_all(), 1)
        self.assertIsNone(self.d.check(self.token))


class TokenRouteTest(ServerBase):
    def test_renouvellement_par_la_route(self):
        _, token = self.enroll()
        self.assertEqual(self.call("POST", "/api/token", {})[0], 401)
        status, body, _ = self.call("POST", "/api/token", {}, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/api/ping", token=body["token"])[0], 200)
        self.assertEqual(self.call("GET", "/api/ping", token=token)[0], 401)
        self.assertIn("token_rotate", str(self.audit.last(5)))
        self.assertNotIn(body["token"], str(self.audit.last(20)))


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

    def test_list_et_revoke_ignorent_les_variables_reseau(self):  # révoquer un téléphone perdu ne doit jamais être bloqué
        with mock.patch.dict("os.environ", {"JARVIS_TS_HOST": "*.x", "JARVIS_PORT": "abc"}):
            self.assertEqual(self.run_cli(["device", "list"], tty=True)[0], 0)
            self.assertEqual(self.run_cli(["device", "revoke", "999"], tty=True)[0], 1)  # introuvable, pas code 2

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

    def test_revoke_all(self):
        tokens = [self.devices.enroll(self.devices.new_code(), n)[1] for n in ("tel", "pc")]
        self.assertEqual(self.run_cli(["device", "revoke", "all"], tty=False)[0], 1)  # terminal exigé
        code, out = self.run_cli(["device", "revoke", "all"], tty=True)
        self.assertEqual((code, all(self.devices.check(t) is None for t in tokens)), (0, True))
        self.assertIn("2 appareil(s)", out)

    def test_url_d_enrolement_dans_le_fragment(self):
        with mock.patch.object(cli, "ts_host_from_env", return_value=TS):
            code, out = self.run_cli(["device", "add"], tty=True)
        self.assertEqual(code, 0)
        self.assertRegex(out, rf"https://{re.escape(TS)}/#code=[A-Za-z0-9_-]{{20,}}")
        self.assertNotIn("code=", str(self.audit.last(10)))  # jamais dans le journal
        with mock.patch.object(cli, "ts_host_from_env", return_value=None):
            self.assertIn("http://127.0.0.1:", self.run_cli(["device", "add"], tty=True)[1])

    def test_usage_invalide(self):
        for argv in (["device"], ["device", "revoke", "abc"], ["device", "add", "extra"]):
            self.assertEqual(self.run_cli(argv, tty=True)[0], 2, argv)


if __name__ == "__main__":
    unittest.main()


class MemoryRemindersTest(ServerBase):
    """Écrans Souvenirs et Rappels de Réglages : lecture, suppression par numéro, journal sans texte."""

    def setUp(self):
        super().setUp()
        from jarvis.core import memory, reminders
        memory.load(self.audit)
        reminders.load(self.audit)
        self.memory, self.reminders = memory, reminders
        self.token = self.enroll()[1]

    def test_authentification_exigee(self):
        for method, path, body in (("GET", "/api/memory", None), ("POST", "/api/memory/forget", {"id": 1}),
                                   ("GET", "/api/reminders", None), ("POST", "/api/reminders/cancel", {"id": 1})):
            self.assertEqual(self.call(method, path, body)[0], 401, path)

    def test_souvenirs_lus_puis_oublies_sans_texte_au_journal(self):
        n = self.memory.add("j'aime le café noir")
        status, body, _ = self.call("GET", "/api/memory", token=self.token)
        self.assertEqual((status, body), (200, {"facts": [{"id": n, "text": "j'aime le café noir"}]}))
        self.assertEqual(self.call("POST", "/api/memory/forget", {"id": n}, token=self.token)[0], 200)
        self.assertEqual(self.call("GET", "/api/memory", token=self.token)[1], {"facts": []})
        self.assertEqual(self.call("POST", "/api/memory/forget", {"id": n}, token=self.token)[0], 404)
        with self.audit.lock:
            dump = str(self.audit.db.execute("SELECT * FROM audit").fetchall())
        self.assertIn("memory_forget", dump)
        self.assertNotIn("café", dump)

    def test_oubli_par_mot_ou_id_invalide_refuse(self):
        self.memory.add("rendez-vous dentiste")
        for bad in ({"id": "dentiste"}, {"id": 0}, {"id": True}, {"id": 1.5}, {}):
            self.assertEqual(self.call("POST", "/api/memory/forget", bad, token=self.token)[0], 422, bad)
        self.assertEqual(len(self.memory.facts()), 1)

    def test_rappels_lus_et_annules_briefing_intouchable(self):
        due = time.time() + 600
        rid = self.reminders.add(due, "sortir le pain", "reminder")
        bid = self.reminders.add(due + 60, "briefing", "briefing")
        status, body, _ = self.call("GET", "/api/reminders", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual([x["id"] for x in body["reminders"]], [rid, bid])
        self.assertEqual(self.call("POST", "/api/reminders/cancel", {"id": bid}, token=self.token)[0], 404)
        self.assertEqual(self.call("POST", "/api/reminders/cancel", {"id": rid}, token=self.token)[0], 200)
        self.assertEqual([x["id"] for x in self.reminders.pending() and
                          self.call("GET", "/api/reminders", token=self.token)[1]["reminders"]], [bid])
        with self.audit.lock:
            dump = str(self.audit.db.execute("SELECT * FROM audit").fetchall())
        self.assertIn("reminder_cancel", dump)
        self.assertNotIn("pain", dump)
