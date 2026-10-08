"""Phase 3, étape 5b : clés d'accès WebAuthn (authentificateur logiciel ES256), N3 dans le chat et abaisser un niveau."""
import hashlib
import json
import os
import threading
import time
import unittest
from unittest import mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from jarvis import server
from jarvis.core import chat as chat_mod, levels, webauthn
from jarvis.core.chat import Chat
from jarvis.core.devices import Devices
from jarvis.core.tools import REGISTRY, Level, tool
from jarvis.core.webauthn import Passkeys, b64u, cbor, UP, UV, AT
from test_chat import ChatBase, wait_for
from test_server import ServerBase, free_port

RP = "pc-test.tail1234.ts.net"
ORIGIN = f"https://{RP}"


@tool("test_wa_light", "lumière de test", Level.N1)
def _light():
    return "ok"


def enc(v) -> bytes:
    """Encodeur CBOR minimal pour fabriquer ce qu'un authentificateur renvoie."""
    def head(kind, n):
        return bytes([kind << 5 | n]) if n < 24 else bytes([kind << 5 | 24, n]) if n < 256 else bytes([kind << 5 | 25]) + n.to_bytes(2, "big")
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        return head(3, len(v.encode())) + v.encode()
    return head(5, len(v)) + b"".join(enc(k) + enc(x) for k, x in v.items())


class Authn:
    """Un authentificateur logiciel : une clé P-256, un compteur, des drapeaux réglables."""
    def __init__(self, rp=RP):
        self.key, self.cred_id, self.count, self.rp = ec.generate_private_key(ec.SECP256R1()), os.urandom(16), 0, rp

    def _auth(self, flags, attested):
        data = hashlib.sha256(self.rp.encode()).digest() + bytes([flags]) + self.count.to_bytes(4, "big")
        if attested:
            n = self.key.public_key().public_numbers()
            cose = {1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")}
            data += bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + enc(cose)
        return data

    def create(self, options, origin=ORIGIN, flags=UP | UV | AT, fmt="none", kind="webauthn.create") -> dict:
        client = json.dumps({"type": kind, "challenge": options["challenge"], "origin": origin}).encode()
        att = enc({"fmt": fmt, "attStmt": {}, "authData": self._auth(flags, True)})
        return {"clientDataJSON": b64u(client), "attestationObject": b64u(att)}

    def get(self, options, origin=ORIGIN, flags=UP | UV, count=None, kind="webauthn.get", sign_with=None) -> dict:
        self.count = self.count + 1 if count is None else count
        client = json.dumps({"type": kind, "challenge": options["challenge"], "origin": origin}).encode()
        auth = self._auth(flags, False)
        sig = (sign_with or self.key).sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cred_id), "clientDataJSON": b64u(client), "authenticatorData": b64u(auth), "signature": b64u(sig)}


class CborTest(unittest.TestCase):
    def test_aller_retour(self):
        value = {1: 2, -2: b"\x01" * 32, "fmt": "none", 3: -7, "n": 300}
        self.assertEqual(cbor(enc(value)), (value, len(enc(value))))

    def test_entrees_invalides_refusees(self):
        for bad in (b"", b"\x5f", b"\x1b" + bytes(8), b"\x44ab", b"\xa1\x01", b"\xc1\x01", b"\x81" * 20 + b"\x01"):
            with self.assertRaises(ValueError, msg=bad):
                cbor(bad)


class PasskeysTest(unittest.TestCase):
    def setUp(self):
        self.devices = Devices(":memory:")
        self.pk = Passkeys(self.devices, RP)
        self.dev = self.add_device("tel")
        self.a = Authn()

    def add_device(self, name):
        return self.devices.db.execute("INSERT INTO devices (name, token_hash, created) VALUES (?, ?, 0)", (name, name)).lastrowid

    def register(self, authn=None, device=None, **kw):
        device = device or self.dev
        self.assertTrue(self.pk.open_window(device))
        return self.pk.register(device, **(authn or self.a).create(self.pk.creation_options(device, "tel"), **kw))

    def assertion(self, action="a", device=None, **kw):
        return (device or self.dev), action, self.a.get(self.pk.request_options(device or self.dev, action), **kw)

    def test_enregistrement_exige_la_fenetre_du_pc(self):
        self.assertIsNone(self.pk.creation_options(self.dev, "tel"))
        self.assertFalse(self.pk.open_window(999))
        self.assertTrue(self.register())
        self.assertTrue(self.pk.has(self.dev))

    def test_la_fenetre_ne_sert_qu_une_fois(self):
        self.pk.open_window(self.dev)
        first = self.a.create(self.pk.creation_options(self.dev, "tel"))
        second = Authn().create(self.pk.creation_options(self.dev, "tel"))  # 2 défis valides, 1 seule fenêtre
        self.assertTrue(self.pk.register(self.dev, **first))
        self.assertFalse(self.pk.register(self.dev, **second))

    def test_enregistrements_refuses(self):
        cases = {"origine": dict(origin="https://evil.example"), "sans verification utilisateur": dict(flags=UP | AT),
                 "attestation non none": dict(fmt="packed"), "mauvais type": dict(kind="webauthn.get")}
        for name, kw in cases.items():
            with self.subTest(name):
                self.assertFalse(self.register(**kw))
                self.assertFalse(self.pk.has(self.dev))

    def test_enregistrement_mauvais_rp_ou_defi_rejoue(self):
        self.assertFalse(self.register(Authn("autre.ts.net")))
        self.pk.open_window(self.dev)
        reply = self.a.create(self.pk.creation_options(self.dev, "tel"))
        self.assertTrue(self.pk.register(self.dev, **reply))
        self.pk.open_window(self.dev)
        self.assertFalse(self.pk.register(self.dev, **reply))  # même défi : déjà consommé

    def test_assertion_valide_puis_rejouee(self):
        self.register()
        reply = self.a.get(self.pk.request_options(self.dev, "confirm:1"))
        self.assertTrue(self.pk.verify(self.dev, "confirm:1", reply))
        self.assertFalse(self.pk.verify(self.dev, "confirm:1", reply))

    def test_assertion_liee_a_l_action_et_a_l_appareil(self):
        self.register()
        other = self.add_device("autre")
        options = self.pk.request_options(self.dev, "confirm:1")
        reply = self.a.get(options)
        self.assertFalse(self.pk.verify(self.dev, "confirm:2", reply))  # le défi est brûlé même après l'échec
        self.assertFalse(self.pk.verify(self.dev, "confirm:1", reply))
        reply = self.a.get(self.pk.request_options(self.dev, "confirm:1"))
        self.assertFalse(self.pk.verify(other, "confirm:1", reply))
        self.assertIsNone(self.pk.request_options(other, "x"))  # l'autre appareil n'a aucune clé

    def test_assertions_refusees(self):
        self.register()
        cases = {"origine": dict(origin="https://evil.example"), "sans verification utilisateur": dict(flags=UP),
                 "mauvais type": dict(kind="webauthn.create"), "autre clé": dict(sign_with=ec.generate_private_key(ec.SECP256R1()))}
        for name, kw in cases.items():
            with self.subTest(name):
                self.assertFalse(self.pk.verify(*self.assertion(**kw)))

    def test_champs_alteres_refuses(self):
        self.register()
        for field in ("signature", "authenticatorData", "clientDataJSON", "id"):
            with self.subTest(field):
                device, action, reply = self.assertion()
                reply[field] = b64u(b"x" * 40)
                self.assertFalse(self.pk.verify(device, action, reply))
        device, action, reply = self.assertion()
        reply["signature"] = "***"
        self.assertFalse(self.pk.verify(device, action, reply))
        self.assertFalse(self.pk.verify(self.dev, "a", {}))

    def test_compteur_qui_recule_refuse(self):
        self.register()
        self.assertTrue(self.pk.verify(*self.assertion(count=5)))
        self.assertFalse(self.pk.verify(*self.assertion(count=5)))
        self.assertFalse(self.pk.verify(*self.assertion(count=3)))
        self.assertTrue(self.pk.verify(*self.assertion(count=6)))

    def test_compteur_a_zero_accepte(self):  # clés d'accès synchronisées : le compteur reste à 0
        self.register()
        self.assertTrue(self.pk.verify(*self.assertion(count=0)))
        self.assertTrue(self.pk.verify(*self.assertion(count=0)))

    def test_defi_expire(self):
        self.register()
        device, action, reply = self.assertion()
        with mock.patch.object(webauthn, "_now", return_value=time.monotonic() + webauthn.CHALLENGE_TTL_S + 1):
            self.assertFalse(self.pk.verify(device, action, reply))

    def test_appareil_revoque(self):
        self.register()
        device, action, reply = self.assertion()
        self.devices.revoke(self.dev)
        self.assertFalse(self.pk.verify(device, action, reply))
        self.assertFalse(self.pk.has(self.dev))

    def test_un_appareil_ne_evince_pas_les_defis_des_autres(self):
        other = self.add_device("autre")
        self.register()
        self.register(Authn(), other)
        mine = self.a.get(self.pk.request_options(self.dev, "a"))
        for _ in range(webauthn.CHALLENGES_MAX * 2):
            self.pk.request_options(other, "spam")
        self.assertLessEqual(sum(v[0] == other for v in self.pk.challenges.values()), webauthn.CHALLENGES_PER_DEVICE)
        self.assertTrue(self.pk.verify(self.dev, "a", mine))

    def test_fenetres_expirees_purgees(self):
        other = self.add_device("autre")
        self.pk.open_window(other)
        self.devices.db.execute("UPDATE passkey_windows SET expires = 0")
        self.pk.open_window(self.dev)
        self.assertEqual(self.devices.db.execute("SELECT device_id FROM passkey_windows").fetchall(), [(self.dev,)])

    def test_sans_rp_id_tout_est_refuse(self):
        pk = Passkeys(self.devices, None)
        self.assertTrue(pk.open_window(self.dev))
        self.assertIsNone(pk.creation_options(self.dev, "tel"))
        self.assertFalse(pk.has(self.dev))


class WebAuthnServerBase(ChatBase):
    """Serveur sur le nom Tailscale (le seul où WebAuthn marche) ; les appels portent Host et Origin HTTPS."""
    def setUp(self):
        ServerBase.setUp(self)
        self.srv.should_exit = True
        time.sleep(0.3)
        self.chat = Chat(self.audit)
        self.port = free_port()
        self.srv = server.make_server(self.devices, self.audit, self.port, self.chat, self.web, RP)
        threading.Thread(target=self.srv.run, daemon=True).start()
        wait_for(lambda: self.srv.started)
        code = self.devices.new_code()
        status, body, _ = ServerBase.call(self, "POST", "/api/enroll", {"code": code, "name": "tel"}, Host=RP, Origin=ORIGIN)
        self.assertEqual(status, 200)
        self.device, self.token = body["id"], body["token"]
        self.calls = []
        self.a = Authn()
        self.addCleanup(setattr, levels, "_audit", None)

    def call(self, method, path, body=None, token=None, **headers):
        return ServerBase.call(self, method, path, body, token or self.token, **{"Host": RP, "Origin": ORIGIN, **headers})

    def register_key(self):
        Passkeys(self.devices, None).open_window(self.device)
        status, options, _ = self.call("POST", "/api/passkey/options", {})
        self.assertEqual(status, 200)
        return self.call("POST", "/api/passkey", self.a.create(options))[0]


class PasskeyRoutesTest(WebAuthnServerBase):
    def test_etat_et_enregistrement(self):
        self.assertEqual(self.call("GET", "/api/passkey")[1], {"enabled": True, "registered": False})
        self.assertEqual(self.call("POST", "/api/passkey/options", {})[0], 403)  # aucune fenêtre ouverte depuis le PC
        self.assertEqual(self.register_key(), 200)
        self.assertEqual(self.call("GET", "/api/passkey")[1], {"enabled": True, "registered": True})
        self.assertIn("clé d'accès enregistrée", str(self.audit.last(3)))

    def test_enregistrement_refuse_journalise(self):
        Passkeys(self.devices, None).open_window(self.device)
        _, options, _ = self.call("POST", "/api/passkey/options", {})
        bad = self.a.create(options, origin="https://evil.example")
        self.assertEqual(self.call("POST", "/api/passkey", bad)[0], 403)
        self.assertIn("enregistrement refusé", str(self.audit.last(3)))

    def test_authentification_obligatoire(self):
        for method, path in (("GET", "/api/passkey"), ("POST", "/api/passkey/options"), ("GET", "/api/levels")):
            self.assertEqual(self.call(method, path, {} if method == "POST" else None, token="x" * 20)[0], 401)


class SansNomTailscaleTest(ChatBase):
    def test_webauthn_desactive_et_n3_refuse(self):
        self.assertEqual(self.call("GET", "/api/passkey", token=self.token)[1], {"enabled": False, "registered": False})
        Passkeys(self.devices, None).open_window(self.device)
        self.assertEqual(self.call("POST", "/api/passkey/options", {}, token=self.token)[0], 403)  # même avec une fenêtre ouverte
        self.assertEqual(self.call("POST", "/api/levels/challenge", {"tool": "test_wa_light", "level": 1}, token=self.token)[0], 403)


class N3ChatTest(WebAuthnServerBase):
    def setUp(self):
        super().setUp()
        self.n3 = mock.Mock(level=Level.N3, preview=lambda args: "ouvrir la serrure")
        self.n3.name = "serrure"
        self.outcomes = []

        def ask(text, *, audit, confirm, strong_auth, source):
            ok = confirm(self.n3, {}) is True and strong_auth(self.n3, {}) is True
            self.outcomes.append(ok)
            self.outcomes.append(strong_auth(self.n3, {}))  # une assertion ne sert qu'une fois
            return "ouvert" if ok else "refusé"
        patch = mock.patch.object(chat_mod, "ask", ask)
        patch.start()
        self.addCleanup(patch.stop)

    def run_n3(self, answer, token=None):
        job = self.start(token=token)[1]["job"]
        pending = wait_for(lambda: self.poll(job, token)[1]["pending"])
        body = {"approve": True, **({"assertion": answer(pending)} if answer else {})}
        self.assertEqual(self.call("POST", f"/api/confirm/{pending['id']}", body, token=token)[0], 200)
        done = wait_for(lambda: (lambda r: r[1] if r[1] and r[1]["status"] == "done" else None)(self.poll(job, token)))
        return pending, done["answer"]

    def test_n3_sans_cle_refuse_sans_demander(self):
        job = self.start()[1]["job"]
        result = self.done(job)
        self.assertEqual((result["answer"], result["pending"]), ("refusé", None))
        self.assertIn("aucune clé d'accès", str(self.audit.last(10)))

    def test_n3_avec_assertion_valide(self):
        self.register_key()
        pending, answer = self.run_n3(lambda p: self.a.get(p["webauthn"]))
        self.assertEqual((pending["level"], answer, self.outcomes), (3, "ouvert", [True, False]))
        self.assertEqual(pending["webauthn"]["rpId"], RP)

    def test_n3_sans_assertion_vaut_refus(self):
        self.register_key()
        self.assertEqual(self.run_n3(None)[1], "refusé")

    def test_n3_assertion_d_une_autre_demande_refusee(self):
        self.register_key()
        foreign = self.chat.passkeys.request_options(self.device, "confirm:autre")
        self.assertEqual(self.run_n3(lambda p: self.a.get(foreign))[1], "refusé")

    def test_n3_mauvaise_signature_refusee_et_journalisee(self):
        self.register_key()
        other = ec.generate_private_key(ec.SECP256R1())
        self.assertEqual(self.run_n3(lambda p: self.a.get(p["webauthn"], sign_with=other))[1], "refusé")
        self.assertIn("assertion absente ou invalide", str(self.audit.last(10)))

    def test_n3_appareil_sans_cle_refuse_meme_si_un_autre_en_a_une(self):
        self.register_key()
        code = self.devices.new_code()
        _, body, _ = ServerBase.call(self, "POST", "/api/enroll", {"code": code, "name": "autre"}, Host=RP, Origin=ORIGIN)
        job = self.start(token=body["token"])[1]["job"]
        done = wait_for(lambda: (lambda r: r[1] if r[1] and r[1]["status"] == "done" else None)(self.poll(job, body["token"])))
        self.assertEqual((done["answer"], done["pending"]), ("refusé", None))

    def test_le_n2_ne_demande_pas_de_cle(self):
        def ask(text, *, audit, confirm, strong_auth, source):
            return str(confirm(REGISTRY["kill_process"], {"pid": 4242, "name": "notepad.exe"}))
        with mock.patch.object(chat_mod, "ask", ask):
            job = self.start()[1]["job"]
            pending = self.pending(job)
            self.assertEqual((pending["level"], pending["webauthn"]), (2, None))
            self.call("POST", f"/api/confirm/{pending['id']}", {"approve": True})
            self.assertEqual(self.done(job)["answer"], "True")


class LevelsRoutesTest(WebAuthnServerBase):
    def level(self, name="test_wa_light"):
        return next(r["level"] for r in self.call("GET", "/api/levels")[1]["levels"] if r["tool"] == name)

    def set(self, level, assertion=None):
        return self.call("POST", "/api/levels", {"tool": "test_wa_light", "level": level,
                                                 **({"assertion": assertion} if assertion else {})})

    def test_liste_avec_planchers(self):
        rows = {r["tool"]: r for r in self.call("GET", "/api/levels")[1]["levels"]}
        self.assertEqual((rows["delete_file"]["floor"], rows["test_wa_light"]["level"]), (2, 1))
        self.assertEqual((rows["delete_file"]["title"], rows["delete_file"]["group"]), ("Supprimer un fichier", "PC"))

    def test_relever_est_libre_abaisser_exige_une_assertion(self):
        self.assertEqual(self.set(2)[0], 200)
        self.assertTrue(self.audit.last(1)[0][1].startswith("pwa:"))  # l'appareil est journalisé
        self.assertEqual(self.level(), 2)
        self.assertEqual(self.set(1)[0], 403)  # sans assertion
        self.assertTrue(self.audit.last(1)[0][1].startswith("pwa:"))
        self.assertEqual(self.level(), 2)
        self.register_key()
        status, options, _ = self.call("POST", "/api/levels/challenge", {"tool": "test_wa_light", "level": 1})
        self.assertEqual(status, 200)
        self.assertEqual(self.set(1, self.a.get(options))[0], 200)
        self.assertEqual(self.level(), 1)

    def test_assertion_liee_au_niveau_demande(self):
        self.set(3)
        self.register_key()
        _, options, _ = self.call("POST", "/api/levels/challenge", {"tool": "test_wa_light", "level": 2})
        self.assertEqual(self.set(1, self.a.get(options))[0], 403)  # signée pour N2, utilisée pour N1
        self.assertEqual(self.level(), 3)
        self.assertIn("assertion invalide", str(self.audit.last(5)))

    def test_defi_sans_cle_et_entrees_invalides(self):
        self.assertEqual(self.call("POST", "/api/levels/challenge", {"tool": "test_wa_light", "level": 1})[0], 403)
        for body in ({"tool": "test_wa_light", "level": "1"}, {"tool": "test_wa_light", "level": 4}, {"tool": "../x", "level": 1}):
            self.assertEqual(self.call("POST", "/api/levels", body)[0], 422, body)
        self.assertEqual(self.call("POST", "/api/levels", {"tool": "inconnu", "level": 1})[0], 422)
        self.assertEqual(self.call("POST", "/api/levels", {"tool": "delete_file", "level": 1})[0], 422)  # plancher


if __name__ == "__main__":
    unittest.main()
