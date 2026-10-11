import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import binance


class SignTest(unittest.TestCase):
    def test_vecteur_de_la_doc_binance(self):
        secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
        q = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
        self.assertEqual(binance.sign(q, secret), "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71")


class KeysTest(unittest.TestCase):
    def test_environnement_prioritaire_puis_dotenv(self):
        with tempfile.TemporaryDirectory() as t:
            env = Path(t) / ".env"
            env.write_text('BINANCE_API_KEY="k1"\nBINANCE_API_SECRET=s1\n', encoding="utf-8")
            self.assertEqual(binance.load_keys({}, env), ("k1", "s1"))
            self.assertEqual(binance.load_keys({"BINANCE_API_KEY": "e"}, env), ("e", "s1"))

    def test_absentes(self):
        self.assertIsNone(binance.load_keys({}, Path("introuvable.env")))


class WindowsTest(unittest.TestCase):
    def test_couverture_sans_trou_ni_chevauchement(self):
        w = list(binance.windows(0, 100 * binance.DAY_MS))
        self.assertEqual(w[0][0], 0)
        self.assertEqual(w[-1][1], 100 * binance.DAY_MS)
        for (_, end), (start, _) in zip(w, w[1:]):
            self.assertEqual(start, end + 1)
        self.assertTrue(all(b - a < binance.WINDOW_DAYS * binance.DAY_MS for a, b in w))


class FetchTest(unittest.TestCase):
    def test_une_categorie_en_echec_n_arrete_pas_les_autres(self):
        def get(path, params, keys):
            if "fiat/orders" in path:
                raise RuntimeError("HTTP 401 Invalid API-key")
            if path == "/api/v3/account":
                return {"balances": [{"asset": "BTC", "free": "0.1", "locked": "0"}, {"asset": "XRP", "free": "0", "locked": "0"}]}
            if path == "/api/v3/myTrades" and params["symbol"] == "BTCEUR":
                return [{"id": 7, "qty": "0.1"}]
            return []
        r = binance.fetch_all(("k", "s"), get, now_ms=40 * binance.DAY_MS + int(binance.START.timestamp() * 1000), pause=lambda s: None)
        self.assertIn("fiat_deposits", r["errors"])
        self.assertEqual([b["asset"] for b in r["data"]["spot_balances"]], ["BTC"])
        self.assertEqual(r["data"]["spot_trades"], [{"id": 7, "qty": "0.1", "symbol": "BTCEUR"}])

    def test_quota_429_reessaye_apres_pause(self):
        calls, pauses = [], []

        def get(path, params, keys):
            calls.append(path)
            if len(calls) == 1:
                raise RuntimeError("HTTP 429 Too many requests")
            return {"data": []}
        r = binance.fetch_all(("k", "s"), get, now_ms=int(binance.START.timestamp() * 1000) + binance.DAY_MS,
                              pause=pauses.append, only={"fiat_deposits"})
        self.assertEqual(r["errors"], {})
        self.assertIn(60, pauses)

    def test_symbole_inexistant_ignore(self):
        def get(path, params, keys):
            raise RuntimeError("HTTP 400 Invalid symbol.")
        r = binance.fetch_all(("k", "s"), get, pause=lambda s: None, only={"spot_trades"})
        self.assertEqual(r["errors"], {})

    def test_run_fusionne_les_categories_non_relues(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "h.json"
            out.write_text('{"data": {"convert": [1]}}', encoding="utf-8")
            r = binance.run(("k", "s"), lambda *a: {"data": []}, out, only={"fiat_deposits"}, pause=lambda s: None)
            self.assertEqual(r["data"]["convert"], [1])
            self.assertEqual(r["data"]["fiat_deposits"], [])

    def test_run_sans_cles(self):
        with mock.patch.object(binance, "load_keys", return_value=None), self.assertRaises(RuntimeError):
            binance.run()


class CostTest(unittest.TestCase):
    ROWS = {
        "convert": [
            {"orderStatus": "SUCCESS", "fromAsset": "EUR", "fromAmount": "100", "toAsset": "USDT", "toAmount": "110"},
            {"orderStatus": "SUCCESS", "fromAsset": "EUR", "fromAmount": "50", "toAsset": "BTC", "toAmount": "0.002"},
            {"orderStatus": "FAILED", "fromAsset": "EUR", "fromAmount": "999", "toAsset": "ETH", "toAmount": "9"},
        ],
        "auto_invest": [
            {"transactionStatus": "SUCCESS", "targetAsset": "BTC", "targetAssetAmount": "0.001", "sourceAsset": "USDT", "sourceAssetAmount": "11"},
            {"transactionStatus": "FAILED", "targetAsset": "BTC", "targetAssetAmount": "1", "sourceAsset": "USDT", "sourceAssetAmount": "999"},
            {"transactionStatus": "SUCCESS", "targetAsset": "SAND", "targetAssetAmount": "5", "sourceAsset": "USDT", "sourceAssetAmount": "5"},
        ],
    }

    def test_prix_de_revient(self):
        b = binance.cost_basis(self.ROWS)
        self.assertAlmostEqual(b["BTC"]["invested"], 50 + 11 * 100 / 110)  # 1 USDT = 100/110 €
        self.assertAlmostEqual(b["BTC"]["bought"], 0.003)
        self.assertEqual(b["ETH"], {"invested": 0.0, "bought": 0.0})  # ordre échoué ignoré

    def test_enrich_ajoute_la_plus_value(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "h.json"
            f.write_text(json.dumps({"data": self.ROWS}), encoding="utf-8")
            c = {"assets": [{"asset": "BTC", "eur": 160.0}, {"asset": "ETH", "eur": 10.0}], "errors": []}
            out = binance.enrich(c, f)
            self.assertEqual(out["assets"][0]["invested"], 60.0)
            self.assertEqual(out["assets"][0]["gain"], 100.0)
            self.assertNotIn("gain", out["assets"][1])  # rien d'investi : pas de %
        self.assertIs(binance.enrich(None), None)

    def test_enrich_sans_fichier(self):
        c = {"assets": [{"asset": "BTC", "eur": 1.0}], "errors": []}
        self.assertEqual(binance.enrich(c, Path("introuvable.json")), c)


class DailyTest(unittest.TestCase):
    def setUp(self):
        binance._refresh["tried"] = 0.0

    def test_rafraichit_si_vieux_une_seule_fois_par_heure(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(binance, "load_keys", return_value=("k", "s")):
            f = Path(t) / "h.json"
            f.write_text("{}", encoding="utf-8")
            mtime = f.stat().st_mtime
            ran = []
            run = lambda fn: fn()
            self.assertFalse(binance.refresh_if_stale(f, now=lambda: mtime + 3600, runner=lambda **k: ran.append(k), start=run))
            self.assertTrue(binance.refresh_if_stale(f, now=lambda: mtime + 90_000, runner=lambda **k: ran.append(k), start=run))
            self.assertFalse(binance.refresh_if_stale(f, now=lambda: mtime + 90_100, runner=lambda **k: ran.append(k), start=run))
            self.assertEqual(ran, [{"only": binance.DAILY}])

    def test_pas_de_fichier_ou_pas_de_cle(self):
        self.assertFalse(binance.refresh_if_stale(Path("introuvable.json")))
        with tempfile.TemporaryDirectory() as t, mock.patch.object(binance, "load_keys", return_value=None):
            f = Path(t) / "h.json"
            f.write_text("{}", encoding="utf-8")
            self.assertFalse(binance.refresh_if_stale(f, now=lambda: f.stat().st_mtime + 10**6))

    def test_categorie_en_echec_garde_les_anciennes_lignes(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "h.json"
            out.write_text('{"data": {"convert": [1]}}', encoding="utf-8")

            def get(path, params, keys):
                raise RuntimeError("HTTP 401 x")
            r = binance.run(("k", "s"), get, out, only={"convert"}, pause=lambda s: None)
            self.assertEqual(r["data"]["convert"], [1])


if __name__ == "__main__":
    unittest.main()
