"""Portefeuille Trade Republic (portfolio.py) : données synthétiques, cours injectés, aucun réseau."""
import csv
import tempfile
import unittest
from datetime import date
from urllib.parse import unquote
from pathlib import Path

from jarvis.core import portfolio

COLS = ["datetime", "date", "account_type", "type", "name", "symbol", "shares", "amount", "fee", "tax"]
ETF, USD, EUR_STOCK = "IE00B4K48X80", "US0378331005", "FR0000120271"


def row(day, acc, kind, isin, shares="", amount="", fee="", tax=""):
    return dict(zip(COLS, [day + "T10:00:00Z", day, acc, kind, "Nom " + isin, isin, shares, amount, fee, tax]))


ROWS = [
    row("2026-01-02", "DEFAULT", "BUY", ETF, "2", "-100"), row("2026-02-02", "DEFAULT", "BUY", ETF, "2", "-120", "1"),
    row("2026-03-02", "PEA", "BUY", ETF, "1", "-50"),
    row("2026-03-03", "DEFAULT", "DIVIDEND", USD, "1", "0.20", tax="-0.06"),
    row("2026-03-04", "DEFAULT", "CARD_TRANSACTION", "", amount="-5"),
]


def fake_get(url):
    if url.startswith(portfolio.SEARCH):
        return {"quotes": [{"symbol": "X-" + url[-12:]}]}
    sym = unquote(url[len(portfolio.CHART):].split("?")[0])
    if sym == "EURUSD=X":
        return {"chart": {"result": [{"meta": {"regularMarketPrice": 2.0, "currency": "USD"}}]}}
    price = {"X-" + ETF: (80.0, "EUR"), "X-" + USD: (50.0, "USD")}.get(sym)
    if price is None:
        raise OSError("hors ligne")
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price[0], "currency": price[1]}}]}}


class PortfolioTest(unittest.TestCase):
    def setUp(self):
        portfolio._cache.update(at=None, data=None)
        portfolio._tickers.clear()

    def test_cost_includes_fees_and_ignores_other_rows(self):
        a = portfolio.positions(ROWS)
        p = a["Compte-titres"]["pos"][ETF]
        self.assertEqual((p["shares"], p["cost"]), (4.0, 221.0))
        self.assertAlmostEqual(a["Compte-titres"]["dividends"], 0.14)
        self.assertEqual(a["PEA"]["pos"][ETF]["cost"], 50.0)

    def test_sale_uses_weighted_average_cost(self):
        a = portfolio.positions(ROWS + [row("2026-04-01", "DEFAULT", "SELL", ETF, "1", "90")])["Compte-titres"]
        self.assertAlmostEqual(a["realized"], 90 - 221 / 4)
        self.assertEqual(a["pos"][ETF]["shares"], 3.0)

    def test_view_gain_and_percent(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "tr.csv"
            with open(path, "w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, COLS)
                w.writeheader()
                w.writerows(ROWS)
            data = portfolio.view(path, fake_get)
        cto, pea = data["accounts"]
        self.assertEqual((cto["value"], cto["invested"], cto["gain"], cto["pct"]), (320.0, 221.0, 99.0, 44.8))
        self.assertEqual((pea["value"], pea["pct"], pea["missing"]), (80.0, 60.0, 0))

    def test_usd_quote_is_converted_and_missing_quote_falls_back_to_cost(self):
        self.assertEqual(portfolio.price_eur(USD, fake_get), 25.0)
        self.assertIsNone(portfolio.price_eur(EUR_STOCK, fake_get))

    def test_view_none_without_import_and_import_rejects_foreign_csv(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(portfolio.view(Path(d) / "absent.csv", fake_get))
            bad = Path(d) / "bad.csv"
            bad.write_text("a,b\n1,2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                portfolio.import_csv(bad, Path(d) / "out.csv")


    def write(self, d):
        path = Path(d) / "tr.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, COLS)
            w.writeheader()
            w.writerows(ROWS)
        return path

    def test_savings_after_csv_are_added_at_cost_without_base(self):
        sav = [{"date": "2026-03-02", "amount": 9.0, "account": "Compte-titres"},  # déjà dans le CSV
               {"date": "2026-03-05", "amount": 10.0, "account": "Compte-titres"}, {"date": "2026-03-05", "amount": 69.0, "account": "PEA"}]
        with tempfile.TemporaryDirectory() as d:
            data = portfolio.view(self.write(d), fake_get, savings=sav, base_path=Path(d) / "base.json")
        cto, pea = data["accounts"]
        self.assertEqual((cto["value"], cto["invested"]), (330.0, 231.0))
        self.assertEqual((pea["value"], pea["invested"]), (149.0, 119.0))

    def test_base_follows_market_and_later_savings(self):
        with tempfile.TemporaryDirectory() as d:
            path, base = self.write(d), Path(d) / "base.json"
            old = [{"date": "2026-04-01", "amount": 15.0, "account": "Compte-titres"}]
            portfolio.set_base({"Compte-titres": 1000.0, "PEA": 400.0}, old, path, base, fake_get, date(2026, 10, 20))
            sav = old + [{"date": "2026-10-21", "amount": 10.0, "account": "Compte-titres"}, {"date": "2026-10-21", "amount": 69.0, "account": "PEA"}]
            up = lambda u: {"chart": {"result": [{"meta": {"regularMarketPrice": 88.0, "currency": "EUR"}}]}} if u.startswith(portfolio.CHART) else fake_get(u)  # noqa: E731
            data = portfolio.view(path, up, savings=sav, base_path=base, today=date(2026, 10, 22))
        cto, pea = data["accounts"]  # cours +10 % depuis la base
        self.assertEqual((cto["value"], cto["invested"]), (1110.0, 246.0))  # 221 du CSV + 15 + 10
        self.assertEqual((pea["value"], pea["invested"]), (509.0, 119.0))

    def test_old_base_folds_savings_before_the_bank_forgets_them(self):
        with tempfile.TemporaryDirectory() as d:
            path, base = self.write(d), Path(d) / "base.json"
            portfolio.set_base({"Compte-titres": 1000.0, "PEA": 400.0}, [], path, base, fake_get, date(2026, 1, 1))
            sav = [{"date": "2026-01-10", "amount": 10.0, "account": "Compte-titres"}]
            portfolio.view(path, fake_get, savings=sav, base_path=base, today=date(2026, 3, 15))
            portfolio._cache["at"] = None
            data = portfolio.view(path, fake_get, savings=[], base_path=base, today=date(2026, 3, 15))  # la banque l'a oubliée
        self.assertEqual(data["accounts"][0]["value"], 1010.0)

    def test_no_fold_without_recent_bank_read(self):
        with tempfile.TemporaryDirectory() as d:
            path, base = self.write(d), Path(d) / "base.json"
            portfolio.set_base({"Compte-titres": 1000.0, "PEA": 400.0}, [], path, base, fake_get, date(2026, 1, 1))
            portfolio.view(path, fake_get, savings=None, base_path=base, today=date(2026, 3, 15))
            self.assertEqual(portfolio._load_base(base)["date"], "2026-01-01")

    def test_invalid_amounts_and_malformed_base(self):
        with tempfile.TemporaryDirectory() as d:
            path, base = self.write(d), Path(d) / "base.json"
            for bad in (float("nan"), float("inf"), -1.0, "1000"):
                with self.assertRaises(ValueError):
                    portfolio.set_base({"PEA": bad}, [], path, base, fake_get)
            self.assertFalse(base.exists())
            base.write_text('{"date": "2026-01-01"}', encoding="utf-8")
            self.assertEqual(portfolio.view(path, fake_get, base_path=base)["accounts"][0]["value"], 320.0)

    def test_base_refused_without_quotes_and_reset_by_import(self):
        with tempfile.TemporaryDirectory() as d:
            path, base = self.write(d), Path(d) / "base.json"
            with self.assertRaises(ValueError):
                portfolio.set_base({"PEA": 1.0}, [], path, base, lambda u: (_ for _ in ()).throw(OSError()))
            portfolio.set_base({"PEA": 1.0}, [], path, base, fake_get)
            portfolio.import_csv(path, Path(d) / "copie.csv", base)
            self.assertFalse(base.exists())


if __name__ == "__main__":
    unittest.main()
