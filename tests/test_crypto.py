import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import crypto

# Vecteur de test BIP84 (mnémonique « abandon … about ») : compte m/84'/0'/0'
ZPUB = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
XPUB = "xpub6CatWdiZiodmUeTDp8LT5or8nmbKNcuyvz7WyksVFkKB4RHwCD3XyuvPEbvqAQY3rAPshWcMLoP2fMFMKHPJ4ZeZXYVUhLv1VMrjPC7PW6V"  # même clé, préfixe Ledger Live
R0, R1 = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu", "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"
C0 = "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"
ETH = "0x" + "ab" * 20


def stats(funded, spent=0, txs=1):
    return {"chain_stats": {"funded_txo_sum": funded, "spent_txo_sum": spent, "tx_count": txs},
            "mempool_stats": {"funded_txo_sum": 0, "spent_txo_sum": 0, "tx_count": 0}}


def fake_get(used: dict, eth="0xde0b6b3a7640000", price=None):
    """Explorateur simulé : adresses utilisées -> stats, autres vides ; journal des URL appelées."""
    calls = []

    def get(url, body=None):
        calls.append(url)
        if url.startswith(crypto.MEMPOOL):
            return used.get(url[len(crypto.MEMPOOL):], stats(0, txs=0))
        if url == crypto.ETH_RPC:
            return {"result": eth}
        return price if price is not None else {"bitcoin": {"eur": 50000}, "ethereum": {"eur": 2000}}
    get.calls = calls
    return get


def setUpModule():
    mock.patch.object(crypto, "PAUSE_S", 0).start()  # pas de pause réseau en test


def tearDownModule():
    mock.patch.stopall()


class DerivationTest(unittest.TestCase):
    def test_vecteurs_bip84_zpub_et_xpub(self):
        for key in (ZPUB, XPUB):
            k = crypto.parse_xpub(key)
            recv, change = crypto.child(k, 0), crypto.child(k, 1)
            self.assertEqual([crypto.p2wpkh(crypto.child(recv, i)[1]) for i in (0, 1)], [R0, R1])
            self.assertEqual(crypto.p2wpkh(crypto.child(change, 0)[1]), C0)

    def test_cles_invalides(self):
        for bad in ("", ZPUB[:-1] + "t", ZPUB + "1", "0" * 111, "xprv" + ZPUB[4:]):
            with self.assertRaises(ValueError):
                crypto.parse_xpub(bad)


class ConfigTest(unittest.TestCase):
    def cfg(self, text):
        p = Path(tempfile.mkdtemp()) / "crypto.json"
        p.write_text(text, encoding="utf-8")
        return crypto.load_config(p)

    def test_absente_valide_invalide(self):
        self.assertIsNone(crypto.load_config(Path(tempfile.mkdtemp()) / "absent.json"))
        ok = self.cfg(json.dumps({"btc": f" {XPUB} ", "eth": ETH}))
        self.assertEqual((ok["eth"], ok["errors"]), (ETH, []))
        self.assertEqual(ok["btc"], crypto.parse_xpub(XPUB))
        bad = self.cfg(json.dumps({"btc": "xpub123", "eth": "0x12"}))
        self.assertEqual((bad["btc"], bad["eth"], bad["errors"]), (None, None, ["Bitcoin : xpub invalide", "Ethereum : adresse invalide"]))
        self.assertEqual(self.cfg("{pas du json")["errors"], ["crypto.json illisible"])


class BalanceTest(unittest.TestCase):
    def test_somme_et_limite_d_ecart(self):
        get = fake_get({R0: stats(150_000, 50_000), R1: stats(0, 0, txs=2), C0: stats(25_000)})
        self.assertEqual(crypto.btc_balance(crypto.parse_xpub(ZPUB), get), 0.00125)
        mempool = [u for u in get.calls if u.startswith(crypto.MEMPOOL)]
        self.assertEqual(len(mempool), 2 + crypto.GAP + 1 + crypto.GAP)  # chaîne 0 : 2 utilisées puis 20 vides ; chaîne 1 : 1 puis 20

    def test_reponse_explorateur_inattendue(self):
        get = fake_get({R0: {"chain_stats": {"tx_count": 1, "funded_txo_sum": "1"}}})
        with self.assertRaises(ValueError):
            crypto.btc_balance(crypto.parse_xpub(ZPUB), get)

    def test_eth(self):
        self.assertEqual(crypto.eth_balance(ETH, fake_get({})), 1.0)
        for bad in (None, "12", "0xzz", "0x" + "f" * 65):
            with self.assertRaises(ValueError):
                crypto.eth_balance(ETH, fake_get({}, eth=bad))


class RefreshViewTest(unittest.TestCase):
    def setUp(self):
        crypto._state.update(at=None, data=None, busy=False)
        self.cfg = {"btc": crypto.parse_xpub(ZPUB), "eth": ETH, "errors": []}

    def test_valeurs_en_euros(self):
        r = crypto.refresh(self.cfg, fake_get({R0: stats(1_000_000)}))
        self.assertEqual([(a["asset"], a["amount"], a["eur"]) for a in r["assets"]], [("BTC", 0.01, 500.0), ("ETH", 1.0, 2000.0)])
        self.assertEqual(r["errors"], [])

    def test_cours_absent_et_actif_en_echec(self):
        previous = {"assets": [{"asset": "ETH", "name": "Ethereum", "amount": 3.0, "eur": 6000.0}]}
        r = crypto.refresh(self.cfg, fake_get({}, eth="nope", price={"bitcoin": {"eur": "x"}}), previous)
        self.assertEqual(r["assets"], [{"asset": "BTC", "name": "Bitcoin", "amount": 0.0, "eur": None}, previous["assets"][0]])
        self.assertEqual(r["errors"], ["Ethereum : lecture impossible"])

        def down(url, body=None):
            raise OSError("réseau")
        r = crypto.refresh(self.cfg, down)
        self.assertEqual((r["assets"], r["errors"]), ([], ["cours indisponible", "Bitcoin : lecture impossible", "Ethereum : lecture impossible"]))

    def test_vue_cache_15_min(self):
        self.assertIsNone(crypto.view(config=lambda: None))
        now, runs = [1000.0], []
        get = fake_get({})

        def view():
            return crypto.view(config=lambda: self.cfg, get=get, clock=lambda: now[0], start=lambda f: (runs.append(1), f()))
        v = view()
        self.assertEqual((len(v["assets"]), v["refreshing"]), (2, False))
        now[0] += crypto.TTL_S - 1
        view()
        self.assertEqual(len(runs), 1)
        now[0] += 2
        view()
        self.assertEqual(len(runs), 2)

    def test_vue_ne_bloque_pas_pendant_la_lecture(self):
        v = crypto.view(config=lambda: self.cfg, get=fake_get({}), start=lambda f: None)  # lecture lancée, pas finie
        self.assertEqual((v["assets"], v["refreshing"]), ([], True))


if __name__ == "__main__":
    unittest.main()
