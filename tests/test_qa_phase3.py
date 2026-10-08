"""Recette QA de la Phase 3 : refus/expiration journalisés sur le vrai chemin (routeur -> garde), F3, pannes des routes."""
import dataclasses
import threading
import time
import unittest
from unittest import mock

from jarvis import server
from jarvis.core import chat as chat_mod, levels
from jarvis.core.tools import REGISTRY, _registry
from test_chat import wait_for
from test_server import ServerBase
from test_webauthn import ORIGIN, RP, WebAuthnServerBase


class RefusJournalise(WebAuthnServerBase):
    """E8 : tout refus d'une action N2/N3 laisse UNE ligne « refusé » pour l'outil, avec la source de l'appareil."""

    def setUp(self):
        super().setUp()
        self.run_mock = mock.Mock(return_value="fait")
        patch = mock.patch.dict(_registry, {"mute": dataclasses.replace(REGISTRY["mute"], run=self.run_mock)})
        patch.start()
        self.addCleanup(patch.stop)

    def refused(self):
        with self.audit.lock:
            return self.audit.db.execute(
                "SELECT source, level, decision FROM audit WHERE tool = 'mute' AND decision = 'refusé'").fetchall()

    def ask_mute(self, level):
        levels.set_level("mute", level, strong_auth=False)  # relever est libre
        job = self.start("coupe le son")[1]["job"]
        return job, wait_for(lambda: self.poll(job)[1]["pending"])

    def finish(self, job):
        self.done(job)
        self.run_mock.assert_not_called()

    def test_n3_bouton_refuser(self):
        self.register_key()
        job, pending = self.ask_mute(3)
        self.assertEqual(self.decide(pending["id"], False)[0], 200)
        self.finish(job)
        self.assertEqual(self.refused(), [(f"pwa:{self.device}", 3, "refusé")])

    def test_n3_oui_sans_assertion(self):  # empreinte annulée : app.js envoie approve=false ; un client fautif enverrait true
        self.register_key()
        job, pending = self.ask_mute(3)
        self.assertEqual(self.decide(pending["id"], True)[0], 200)
        self.finish(job)
        self.assertEqual(self.refused(), [(f"pwa:{self.device}", 3, "refusé")])

    def test_n3_assertion_illisible_refuse_tout_de_suite(self):  # une exception dans verify() laisserait le job attendre 60 s
        self.register_key()
        job, pending = self.ask_mute(3)
        for junk in ("A", "AAAA", "A" * 1399, "-_-_"):
            junk_assertion = {"id": junk, "clientDataJSON": junk, "authenticatorData": junk, "signature": junk}
            status = self.call("POST", f"/api/confirm/{pending['id']}", {"approve": True, "assertion": junk_assertion})[0]
            if status == 200:
                break
        self.assertEqual(status, 200)
        self.finish(job)
        self.assertEqual(self.refused(), [(f"pwa:{self.device}", 3, "refusé")])

    def test_n3_expiration(self):
        self.register_key()
        with mock.patch.object(chat_mod, "CONFIRM_TTL_S", 0.3):
            job, _ = self.ask_mute(3)
            self.finish(job)
        self.assertEqual(self.refused(), [(f"pwa:{self.device}", 3, "refusé")])
        self.assertIn("expirée", str(self.audit.last(5)))

    def test_n3_sans_cle_refuse_et_journalise(self):
        levels.set_level("mute", 3, strong_auth=False)
        self.finish(self.start("coupe le son")[1]["job"])
        self.assertEqual(self.refused(), [(f"pwa:{self.device}", 3, "refusé")])

    def test_n2_refus_et_expiration(self):
        job, pending = self.ask_mute(2)
        self.decide(pending["id"], False)
        self.finish(job)
        with mock.patch.object(chat_mod, "CONFIRM_TTL_S", 0.3):
            self.finish(self.start("coupe le son")[1]["job"])
        self.assertEqual([r[1:] for r in self.refused()], [(2, "refusé")] * 2)

    def test_appareil_revoque_pendant_la_confirmation(self):
        with mock.patch.object(chat_mod, "CONFIRM_TTL_S", 1.0):
            job, pending = self.ask_mute(2)
            self.devices.revoke(self.device)
            self.assertEqual(self.decide(pending["id"], True)[0], 401)  # ne peut plus rien approuver
            end = wait_for(lambda: self.refused())  # la demande orpheline expire : refus journalisé, rien exécuté
        self.assertEqual(end, [(f"pwa:{self.device}", 2, "refusé")])
        self.run_mock.assert_not_called()


class RenotifieTest(WebAuthnServerBase):
    """F3 : un push envoyé pendant que la PWA est encore visible n'affiche rien ; un second part si la demande attend."""

    def run_with(self, ttl, renotify, answer_after=None):
        calls = []
        push = mock.Mock()
        push.notify = lambda device, audit=None: calls.append(device)
        self.chat.push = push
        ask = lambda text, *, audit, confirm, strong_auth, source: str(  # noqa: E731
            confirm(REGISTRY["kill_process"], {"pid": 4242, "name": "notepad.exe"}))
        with mock.patch.object(chat_mod, "ask", ask), mock.patch.object(chat_mod, "CONFIRM_TTL_S", ttl), \
                mock.patch.object(chat_mod, "RENOTIFY_S", renotify):
            job = self.start()[1]["job"]
            pending = self.pending(job)
            if answer_after is not None:
                time.sleep(answer_after)
                self.decide(pending["id"], False)
            self.done(job)
        return calls

    def test_second_envoi_si_la_demande_attend(self):
        self.assertEqual(self.run_with(1.0, 0.2), [self.device, self.device])

    def test_un_seul_envoi_si_repondu_vite(self):
        self.assertEqual(self.run_with(1.0, 0.5, answer_after=0.0), [self.device])

    def test_pas_de_second_envoi_apres_expiration_courte(self):
        self.assertEqual(self.run_with(0.3, 15), [self.device])

    def test_service_worker_et_message_cle_existante(self):
        from jarvis.server import WEB_DIR
        sw = (WEB_DIR / "sw.js").read_text(encoding="utf-8")
        self.assertIn("renotify: true", sw)  # même tag que « push test » : sans cela, remplacement silencieux sur Android
        js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("InvalidStateError", js)
        self.assertIn("existe déjà", js)


class RoutesRobustesTest(WebAuthnServerBase):
    ROUTES = (("GET", "/api/ping"), ("POST", "/api/chat"), ("GET", "/api/chat/abc"), ("POST", "/api/confirm/abc"),
              ("GET", "/api/audit"), ("GET", "/api/devices"), ("GET", "/api/push"), ("POST", "/api/push"),
              ("POST", "/api/push/unsubscribe"), ("GET", "/api/passkey"), ("POST", "/api/passkey/options"),
              ("POST", "/api/passkey"), ("GET", "/api/levels"), ("POST", "/api/levels/challenge"), ("POST", "/api/levels"))
    VALID = {"/api/chat": {"text": "x"}, "/api/confirm/abc": {"approve": True}, "/api/levels": {"tool": "mute", "level": 1},
             "/api/levels/challenge": {"tool": "mute", "level": 1}, "/api/passkey": {"clientDataJSON": "aa", "attestationObject": "aa"},
             "/api/push": {"endpoint": "https://fcm.googleapis.com/x", "p256dh": "aa", "auth": "aa"}}

    def body(self, method, path):
        return self.VALID.get(path, {}) if method == "POST" else None

    def test_toute_route_exige_un_jeton_valide_puis_non_revoque(self):
        patch = mock.patch.object(server, "AUTH_FAIL_MAX", 10 ** 6)  # sinon le compteur d'échecs répond 429 (testé ailleurs)
        patch.start()
        self.addCleanup(patch.stop)
        for method, path in self.ROUTES:
            body = self.body(method, path)
            self.assertEqual(self.call(method, path, body, token="faux" * 10)[0], 401, (method, path))
            self.assertEqual(self.call(method, path, body, token="x", Authorization="")[0], 401, (method, path))
        self.devices.revoke(self.device)
        for method, path in self.ROUTES:
            self.assertEqual(self.call(method, path, self.body(method, path))[0], 401, (method, path))

    def test_host_ou_origin_faux_sur_toute_route(self):
        for method, path in self.ROUTES:
            body = self.body(method, path)
            self.assertEqual(self.call(method, path, body, Host="evil.example")[0], 400, (method, path))
            self.assertEqual(self.call(method, path, body, Host=RP + ":8443")[0], 400, (method, path))
            if method == "POST":
                for origin in ("https://evil.example", "null", None):
                    self.assertEqual(self.call(method, path, body, Origin=origin)[0], 403, (method, path, origin))

    def test_corps_malformes_jamais_500(self):
        for path in ("/api/chat", "/api/confirm/abc", "/api/push", "/api/passkey", "/api/levels", "/api/levels/challenge",
                     "/api/enroll"):
            for raw in (b"", b"{", b"null", b"[]", b'"x"', b"123", b"\xff\xfe", b'{"text": ' + b"[" * 5000):
                status = self.call("POST", path, raw)[0]
                self.assertIn(status, (400, 401, 422), (path, raw[:20], status))  # 400 : JSON trop imbriqué
        status, body, _ = self.call("POST", "/api/chat", b'{"text": ' + b"[" * 5000)
        self.assertEqual(body, {"detail": "requête invalide"})  # jamais le texte d'erreur par défaut de Starlette
        # Le corps est validé avant le jeton : un client non authentifié apprend seulement « corps invalide » (BUG-P3-04, accepté).
        self.assertEqual(self.call("POST", "/api/chat", {"text": "x"}, token="x" * 20)[0], 401)

    def test_gros_corps_refuse_avant_lecture(self):
        big = b'{"text": "' + b"a" * 9000 + b'"}'
        for path in ("/api/chat", "/api/confirm/abc", "/api/push", "/api/passkey", "/api/levels", "/api/enroll"):
            self.assertEqual(self.call("POST", path, big)[0], 413, path)

    def test_champs_trop_longs_ou_mal_types(self):
        for body in ({"text": "a" * 1001}, {"text": ""}, {"text": 5}):
            self.assertEqual(self.call("POST", "/api/chat", body)[0], 422, body)
        bad_assertion = {"id": "a b", "clientDataJSON": "x", "authenticatorData": "x", "signature": "x"}
        for body in ({"approve": "true"}, {"approve": 1}, {}, {"approve": True, "assertion": "x"},
                     {"approve": True, "assertion": bad_assertion}):
            self.assertEqual(self.call("POST", "/api/confirm/abc", body)[0], 422, body)

    def test_identifiants_hostiles_donnent_404(self):
        for cid in ("a%2F..%2Fb", "x" * 500, "%00", "a%20b"):
            self.assertEqual(self.call("POST", f"/api/confirm/{cid}", {"approve": True})[0], 404, cid)
            self.assertEqual(self.call("GET", f"/api/chat/{cid}")[0], 404, cid)


class RejeuTest(WebAuthnServerBase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(chat_mod, "ask", lambda text, *, audit, confirm, strong_auth, source: str(
            confirm(REGISTRY["kill_process"], {"pid": 4242, "name": "notepad.exe"})))
        patch.start()
        self.addCleanup(patch.stop)

    def test_rejeu_d_une_confirmation_servie(self):
        job = self.start()[1]["job"]
        cid = self.pending(job)["id"]
        self.assertEqual(self.decide(cid, True)[0], 200)
        self.assertEqual(self.done(job)["answer"], "True")
        self.assertEqual(self.decide(cid, True)[0], 404)
        self.assertEqual(self.decide(cid, False)[0], 404)

    def test_double_confirmation_simultanee_une_seule_gagne(self):
        job = self.start()[1]["job"]
        cid = self.pending(job)["id"]
        codes = []
        threads = [threading.Thread(target=lambda: codes.append(self.decide(cid, True)[0])) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(codes).count(200), 1, codes)
        self.done(job)

    def test_confirmation_d_un_autre_appareil_et_apres_expiration(self):
        code = self.devices.new_code()
        _, body, _ = ServerBase.call(self, "POST", "/api/enroll", {"code": code, "name": "autre"}, Host=RP, Origin=ORIGIN)
        with mock.patch.object(chat_mod, "CONFIRM_TTL_S", 0.4):
            job = self.start()[1]["job"]
            cid = self.pending(job)["id"]
            self.assertEqual(self.decide(cid, True, token=body["token"])[0], 404)
            self.done(job)
        self.assertEqual(self.decide(cid, True)[0], 404)


if __name__ == "__main__":
    unittest.main()
