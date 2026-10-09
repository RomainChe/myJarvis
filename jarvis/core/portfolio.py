"""Portefeuille Trade Republic (compte-titres + PEA) pour l'onglet Finances, lecture seule.

Source : l'export « Exportation de transactions » de l'appli, copié par `python -m jarvis portfolio import <fichier.csv>` dans
`~/.jarvis/tr-transactions.csv` (hors dépôt). Le prix de revient suit le prix moyen pondéré par ISIN ; le % est celui de
l'appli : (valeur - investi) / investi, dividendes à part. Cours : Yahoo Finance (sans clé, non officiel), seuls les ISIN
partent. Cache mémoire 15 min. Les noms du CSV sont du contenu externe : jamais interprétés. Pas d'outil LLM ; la lecture est
journalisée par la route (`bank_read`)."""
import csv
import json
import re
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path

CSV = Path.home() / ".jarvis" / "tr-transactions.csv"
SEARCH = "https://query1.finance.yahoo.com/v1/finance/search?quotesCount=10&newsCount=0&q="
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
ACCOUNTS = {"DEFAULT": "Compte-titres", "PEA": "PEA"}
ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
MAX_BYTES, TTL_S, TIMEOUT = 5_000_000, 900, 15
NEEDED = {"account_type", "type", "symbol", "name", "shares", "amount", "fee", "tax", "date"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
_cache = {"at": None, "data": None}
_tickers: dict[str, str | None] = {}  # ISIN -> symbole Yahoo, tant que le processus vit


def _f(s) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def import_csv(src: Path, dest: Path = CSV) -> int:
    """Valide l'export (taille, colonnes) puis le copie ; renvoie le nombre de lignes."""
    src = Path(src)
    if src.stat().st_size > MAX_BYTES:
        raise ValueError("fichier trop gros")
    with open(src, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if not NEEDED <= set(reader.fieldnames or ()):
            raise ValueError("ce n'est pas l'export de transactions Trade Republic")
        n = sum(1 for _ in reader)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    _cache["at"] = None
    return n


def positions(rows) -> dict:
    """{compte: {"pos": {isin: {name, shares, cost}}, "dividends", "realized", "last"}} ; ordres BUY/SELL et DIVIDEND."""
    out = {}
    for r in sorted(rows, key=lambda r: r.get("datetime") or r.get("date") or ""):
        acc = ACCOUNTS.get(r.get("account_type"))
        kind, isin = r.get("type"), r.get("symbol") or ""
        if acc is None or kind not in ("BUY", "SELL", "DIVIDEND") or not ISIN.fullmatch(isin):
            continue
        a = out.setdefault(acc, {"pos": {}, "dividends": 0.0, "realized": 0.0, "last": ""})
        a["last"] = max(a["last"], r.get("date") or "")
        if kind == "DIVIDEND":
            a["dividends"] += _f(r["amount"]) + _f(r["tax"])  # taxe signée (négative)
            continue
        p = a["pos"].setdefault(isin, {"name": (r.get("name") or isin)[:60], "shares": 0.0, "cost": 0.0})
        sh, fee = abs(_f(r["shares"])), abs(_f(r["fee"]))
        if kind == "BUY":
            p["shares"] += sh
            p["cost"] += -_f(r["amount"]) + fee
        elif p["shares"] > 0:  # prix moyen pondéré : le coût sorti est proportionnel aux parts vendues
            sold = min(sh, p["shares"])
            out_cost = p["cost"] * sold / p["shares"]
            a["realized"] += _f(r["amount"]) - fee - out_cost
            p["shares"] -= sold
            p["cost"] -= out_cost
    return out


# ---- cours ---------------------------------------------------------------------------------------------------------------

def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with _opener.open(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read(1_000_000))


def _last(symbol: str, get) -> tuple[float, str] | None:
    try:
        meta = get(CHART + urllib.parse.quote(symbol) + "?range=5d&interval=1d")["chart"]["result"][0]["meta"]
        return float(meta["regularMarketPrice"]), meta["currency"]
    except (KeyError, IndexError, TypeError, ValueError, OSError):
        return None


def price_eur(isin: str, get=_get) -> float | None:
    """Dernier cours en euros : première place cotée en EUR, sinon USD converti. None si introuvable."""
    symbols = [_tickers[isin]] if _tickers.get(isin) else []
    if not symbols:
        try:
            symbols = [q["symbol"] for q in get(SEARCH + isin)["quotes"] if q.get("symbol")]
        except (KeyError, TypeError, OSError):
            return None
    usd = None
    for s in symbols:
        got = _last(s, get)
        if got and got[1] == "EUR":
            _tickers[isin] = s
            return got[0]
        usd = usd or (got if got and got[1] == "USD" else None)
    rate = _last("EURUSD=X", get) if usd else None
    return usd[0] / rate[0] if usd and rate else None


def view(path: Path = CSV, get=_get, clock=time.monotonic) -> dict | None:
    """None si aucun export importé. Position sans cours : comptée à son prix de revient (`missing` la signale)."""
    if _cache["at"] is not None and clock() - _cache["at"] < TTL_S:
        return _cache["data"]
    if not Path(path).exists():
        return None
    with open(path, encoding="utf-8", newline="") as fh:
        pos = positions(csv.DictReader(fh))
    prices, accounts = {}, []
    for name in ACCOUNTS.values():
        a = pos.get(name)
        if not a:
            continue
        value = invested = 0.0
        lines, missing = [], 0
        for isin, p in a["pos"].items():
            if p["shares"] <= 1e-9:
                continue
            if isin not in prices:
                prices[isin] = price_eur(isin, get)
            price = prices[isin]
            missing += price is None
            v = p["shares"] * price if price is not None else p["cost"]
            value, invested = value + v, invested + p["cost"]
            lines.append({"name": p["name"], "value": round(v, 2), "cost": round(p["cost"], 2),
                          "pct": round((v / p["cost"] - 1) * 100, 2) if p["cost"] else None})
        lines.sort(key=lambda x: -x["value"])
        accounts.append({"name": name, "value": round(value, 2), "invested": round(invested, 2),
                         "gain": round(value - invested, 2), "pct": round((value / invested - 1) * 100, 2) if invested else None,
                         "dividends": round(a["dividends"], 2), "realized": round(a["realized"], 2),
                         "last": a["last"], "missing": missing, "positions": lines})
    data = {"accounts": accounts}
    _cache.update(at=clock(), data=data)
    return data
