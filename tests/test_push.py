"""Phase 3, étape 6 : Web Push (chiffrement RFC 8291, VAPID, abonnements, notification de confirmation)."""
import json
import threading
import time
import unittest
import urllib.request
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from jarvis import server
from jarvis.core.devices import Devices
from jarvis.core.push import Push, _NoRedirect, encrypt, endpoint_ok, subject_from_env
from jarvis.core.webauthn import b64u, unb64u
from test_chat import ChatBase, wait_for
from test_server import free_port

FCM = "https://fcm.googleapis.com/fcm/send/abc123"


class Browser:
    """Un abonné simulé : clé P-256 et secret d'authentification, capable de déchiffrer."""
    def __init__(self):
        self.key, self.auth = ec.generate_private_key(ec.SECP256R1()), b"\x07" * 16
        self.p256dh = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def subscription(self):
        return {"endpoint": FCM, "p256dh": b64u(self.p256dh), "auth": b64u(self.auth)}

    def decrypt(self, body: bytes) -> bytes:
        salt, size, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
        theirs, sealed = body[21:21 + idlen], body[21 + idlen:]
        shared = self.key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), theirs))
        ikm = HKDF(hashes.SHA256(), 32, self.auth, b"WebPush: info\0" + self.p256dh + theirs).derive(shared)
        key = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\0").derive(ikm)
        nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\0").derive(ikm)
        plain = AESGCM(key).decrypt(nonce, sealed, None)
        assert size == 4096 and plain.endswith(b"\x02")
        return plain[:-1]


class Store:
    def __init__(self):
        self.d = {}

    def get(self, name):
        return self.d.get(name)

    def put(self, name, value):
        self.d[name] = value


def make_push(devices=None, store=None):
    store = store or Store()
    return Push(devices or Devices(":memory:"), "https://pc-test.tail1234.ts.net", store.get, store.put), store


def add_device(devices, name="tel"):
    return devices.db.execute("INSERT INTO devices (name, token_hash, created) VALUES (?, ?, 0)", (name, name)).lastrowid


class EndpointTest(unittest.TestCase):
    def test_services_connus_seulement(self):
        for ok in (FCM, "https://updates.push.services.mozilla.com/wpush/v2/x", "https://web.push.apple.com/x",
                   "https://wns2-par02p.notify.windows.com/?token=x"):
            self.assertTrue(endpoint_ok(ok), ok)
        for bad in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://localhost/x", "https://evil.example/x",
                    "https://fcm.googleapis.com.evil.example/x", "https://fcm.googleapis.com:8443/x", "https://u:p@fcm.googleapis.com/x",
                    "https://evilgoogleapis.com/x", "https://storage.googleapis.com/x", "https://x.push.apple.com/x",
                    "https://x.push.services.mozilla.com/x", "ftp://fcm.googleapis.com/x", "", "https://fcm.googleapis.com/" + "a" * 600):
            self.assertFalse(endpoint_ok(bad), bad)

    def test_redirections_refusees(self):
        self.assertIsNone(_NoRedirect().redirect_request(urllib.request.Request(FCM), None, 302, "x", {}, "http://127.0.0.1/"))


class PushTest(unittest.TestCase):
    def setUp(self):
        self.devices = Devices(":memory:")
        self.push, self.store = make_push(self.devices)
        self.dev, self.b = add_device(self.devices), Browser()

    def subscribe(self, **kw):
        return self.push.subscribe(self.dev, **{**self.b.subscription(), **kw})

    def test_chiffrement_aller_retour(self):
        for text in (b"{}", b"x" * 1000):
            self.assertEqual(self.b.decrypt(encrypt(text, self.b.p256dh, self.b.auth)), text)

    def test_cle_vapid_creee_une_fois_et_rangee_dans_le_coffre(self):
        public = self.push.public_key()
        self.assertEqual(len(unb64u(public)), 65)
        self.assertEqual(list(self.store.d), ["vapid_key"])
        again, _ = make_push(self.devices, self.store)  # nouveau processus, même coffre
        self.assertEqual(again.public_key(), public)

    def test_jeton_vapid_signe_et_borne_a_l_origine(self):
        header = self.push._vapid(FCM)
        token, key = header[len("vapid t="):].split(", k=")
        head, claims, sig = token.split(".")
        self.assertEqual(key, self.push.public_key())
        raw = unb64u(sig)
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(key))
        pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                   f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
        data = json.loads(unb64u(claims))
        self.assertEqual((data["aud"], data["sub"]), ("https://fcm.googleapis.com", "https://pc-test.tail1234.ts.net"))
        self.assertLessEqual(data["exp"] - time.time(), 12 * 3600)

    def test_abonnements_invalides_refuses(self):
        for kw in ({"endpoint": "https://evil.example/x"}, {"auth": b64u(b"x" * 8)}, {"p256dh": b64u(b"x" * 65)},
                   {"p256dh": "***"}, {"endpoint": "http://fcm.googleapis.com/x"}):
            self.assertFalse(self.subscribe(**kw), kw)
        self.assertFalse(self.push.subscribed(self.dev))

    def test_envoi_chiffre_pour_l_abonne(self):
        self.assertTrue(self.subscribe())
        with mock.patch.object(Push, "_post", return_value=201) as post:
            self.assertTrue(self.push.send(self.dev))
        endpoint, body = post.call_args.args
        self.assertEqual(endpoint, FCM)
        self.assertEqual(json.loads(self.b.decrypt(body)), {"title": "Jarvis", "body": "Une action attend ta confirmation."})

    def test_abonnement_expire_supprime(self):
        self.subscribe()
        with mock.patch.object(Push, "_post", return_value=410):
            self.assertFalse(self.push.send(self.dev))
        self.assertFalse(self.push.subscribed(self.dev))

    def test_erreur_temporaire_garde_l_abonnement(self):
        self.subscribe()
        with mock.patch.object(Push, "_post", return_value=0):
            self.assertFalse(self.push.send(self.dev))
        self.assertTrue(self.push.subscribed(self.dev))

    def test_rien_pour_un_appareil_sans_abonnement_ou_revoque(self):
        with mock.patch.object(Push, "_post") as post:
            self.assertFalse(self.push.send(self.dev))
            self.subscribe()
            self.devices.revoke(self.dev)
            self.assertFalse(self.push.send(self.dev))
        post.assert_not_called()

    def test_cle_vapid_jamais_gardee_si_le_coffre_echoue(self):
        def boom(*_):
            raise OSError("coffre")
        push = Push(Devices(":memory:"), "https://x.test", lambda _: None, boom)
        for _ in range(2):  # le second appel doit retenter, pas servir une clé non persistée
            with self.assertRaises(OSError):
                push.key()

    def test_revoquer_supprime_l_abonnement(self):
        self.subscribe()
        self.devices.revoke(self.dev)
        self.assertFalse(self.push.subscribed(self.dev))

    def test_contact_vapid_neutre_par_defaut_et_valide(self):
        with mock.patch.dict("os.environ", {"JARVIS_PUSH_CONTACT": ""}):
            self.assertEqual(subject_from_env(), "mailto:jarvis@example.invalid")
        with mock.patch.dict("os.environ", {"JARVIS_PUSH_CONTACT": "mailto:moi@exemple.test"}):
            self.assertEqual(subject_from_env(), "mailto:moi@exemple.test")
        with mock.patch.dict("os.environ", {"JARVIS_PUSH_CONTACT": "http://x"}), self.assertRaises(ValueError):
            subject_from_env()

    def test_erreur_http_inattendue_n_est_pas_une_exception(self):
        import http.client
        with mock.patch("urllib.request.OpenerDirector.open", side_effect=http.client.IncompleteRead(b"")):
            self.assertEqual(self.push._post(FCM, b"x"), 0)

    def test_un_seul_abonnement_par_appareil(self):
        self.subscribe()
        other = Browser()
        self.assertTrue(self.push.subscribe(self.dev, **{**other.subscription(), "endpoint": FCM + "2"}))
        self.assertEqual(self.devices.db.execute("SELECT endpoint FROM push_subs").fetchall(), [(FCM + "2",)])


class PushRoutesTest(ChatBase):
    def setUp(self):
        super().setUp()
        self.srv.should_exit = True
        time.sleep(0.3)
        self.push, _ = make_push(self.devices)
        self.chat.push = self.push
        self.port = free_port()
        self.srv = server.make_server(self.devices, self.audit, self.port, self.chat, self.web, None, self.push)
        threading.Thread(target=self.srv.run, daemon=True).start()
        wait_for(lambda: self.srv.started)
        self.device, self.token = self.enroll("tel2")

    def test_authentification_obligatoire(self):
        for method, path in (("GET", "/api/push"), ("POST", "/api/push"), ("POST", "/api/push/unsubscribe")):
            self.assertEqual(self.call(method, path, Browser().subscription() if method == "POST" else None)[0], 401)

    def test_cycle_abonnement(self):
        status, body, _ = self.call("GET", "/api/push", token=self.token)
        self.assertEqual((status, body["subscribed"], len(unb64u(body["key"]))), (200, False, 65))
        self.assertEqual(self.call("POST", "/api/push", Browser().subscription(), token=self.token)[0], 200)
        self.assertTrue(self.call("GET", "/api/push", token=self.token)[1]["subscribed"])
        self.assertEqual(self.call("POST", "/api/push/unsubscribe", {}, token=self.token)[0], 200)
        self.assertFalse(self.call("GET", "/api/push", token=self.token)[1]["subscribed"])
        self.assertIn("notifications activées", str(self.audit.last(5)))

    def test_endpoint_hors_liste_refuse(self):
        sub = {**Browser().subscription(), "endpoint": "https://127.0.0.1/x"}
        self.assertEqual(self.call("POST", "/api/push", sub, token=self.token)[0], 422)

    def test_confirmation_en_attente_notifie_l_appareil_demandeur(self):
        with mock.patch.object(Push, "notify") as notify, self.fake_ask():
            job = self.start()[1]["job"]
            self.decide(self.pending(job)["id"], False)
            self.done(job)
        notify.assert_called_once_with(self.device, self.audit)

    def test_panne_du_service_de_push_n_empeche_rien(self):
        self.push.subscribe(self.device, **Browser().subscription())
        with mock.patch.object(Push, "_post", side_effect=RuntimeError("panne")), self.fake_ask():
            job = self.start()[1]["job"]
            self.decide(self.pending(job)["id"], True)
            self.assertEqual(self.done(job)["answer"], "confirmé")
        self.assertIn("notification non remise", str(wait_for(lambda: self.audit.last(5) if "non remise" in str(self.audit.last(5)) else None)))


if __name__ == "__main__":
    unittest.main()
