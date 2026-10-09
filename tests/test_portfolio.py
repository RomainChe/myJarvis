"""Portefeuille Trade Republic (portfolio.py) : données synthétiques, cours injectés, aucun réseau."""
import csv
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
