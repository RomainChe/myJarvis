"""Portefeuille Trade Republic (compte-titres + PEA) pour l'onglet Finances, lecture seule.

Source : l'export « Exportation de transactions » de l'appli, copié par `python -m jarvis portfolio import <fichier.csv>` dans
`~/.jarvis/tr-transactions.csv` (hors dépôt). Le prix de revient suit le prix moyen pondéré par ISIN ; le % est celui de
l'appli : (valeur - investi) / investi, dividendes à part. Cours : Yahoo Finance (sans clé, non officiel), seuls les ISIN
partent. Base : valeurs du jour saisies par `python -m jarvis portfolio base <cto> <pea>` (`~/.jarvis/tr-base.json`) ; l'épargne
Trade Republic lue par la banque après elle s'y ajoute (budget.investments). Cache mémoire 15 min. Les noms du CSV sont du contenu externe : jamais interprétés. Pas d'outil LLM ; la lecture est
journalisée par la route (`bank_read`)."""
import csv
import json
import math
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

CSV = Path.home() / ".jarvis" / "tr-transactions.csv"
BASE = Path.home() / ".jarvis" / "tr-base.json"  # valeurs saisies par le propriétaire (`portfolio base`)
SEARCH = "https://query1.finance.yahoo.com/v1/finance/search?quotesCount=10&newsCount=0&q="
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
ACCOUNTS = {"DEFAULT": "Compte-titres", "PEA": "PEA"}
ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
MAX_BYTES, TTL_S, TIMEOUT = 5_000_000, 900, 15
FOLD_DAYS, SETTLE_DAYS = 60, 30
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


def import_csv(src: Path, dest: Path = CSV, base_path: Path = BASE) -> int:
    """Valide l'export (taille, colonnes) puis le copie ; renvoie le nombre de lignes. Efface la base : ses cours de
    référence portaient sur les anciennes positions."""
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
    Path(base_path).unlink(missing_ok=True)
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


def _market(path: Path, get) -> list[dict]:
    """Comptes du CSV valorisés aux derniers cours. Position sans cours : comptée à son prix de revient (`missing`)."""
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
        accounts.append({"name": name, "value": value, "invested": invested, "dividends": round(a["dividends"], 2),
                         "realized": round(a["realized"], 2), "last": a["last"], "missing": missing, "positions": lines})
    return accounts


def _added(savings, name: str, after: str, until: str = "9999") -> float:
    return sum(s["amount"] for s in savings if s["account"] == name and after < s["date"] <= until)


def _perf(a: dict, b: dict) -> float:
    """Variation des cours depuis la base, mesurée sur les positions du CSV ; 1 si un cours manque."""
    return a["value"] / b["mkt"] if b["mkt"] and not a["missing"] else 1.0


def _load_base(path: Path) -> dict | None:
    """None si absente ou mal formée : l'onglet retombe sur les positions du CSV au lieu d'échouer."""
    try:
        b = json.loads(Path(path).read_text(encoding="utf-8"))
        date.fromisoformat(b["date"])
        if all(math.isfinite(a[k]) for a in b["accounts"].values() for k in ("value", "invested", "mkt")):
            return b
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def _write(path: Path, base: dict):
    """Écriture atomique : un arrêt en pleine écriture ne doit pas perdre la base saisie."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(base), encoding="utf-8")
    os.replace(tmp, path)


def set_base(values: dict, savings=(), path: Path = CSV, base_path: Path = BASE, get=_get, today: date | None = None):
    """Valeurs du jour lues dans l'appli ({compte: €}). L'investi y ajoute l'épargne lue par la banque depuis l'export."""
    day = (today or date.today()).isoformat()
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1e8 for v in values.values()):
        raise ValueError("montant invalide (nombre entre 0 et 100 000 000)")
    savings = savings or []
    if not Path(path).exists():
        raise ValueError("importe d'abord l'export : python -m jarvis portfolio import <fichier.csv>")
    market = {a["name"]: a for a in _market(path, get)}
    if any(a["missing"] for a in market.values()):
        raise ValueError("cours indisponibles, réessaie plus tard")
    accounts = {}
    for name, value in values.items():
        a = market.get(name, {"value": 0.0, "invested": 0.0, "last": ""})
        accounts[name] = {"value": value, "invested": a["invested"] + _added(savings, name, a["last"], day), "mkt": a["value"]}
    _write(base_path, {"date": day, "accounts": accounts})
    _cache["at"] = None


def _fold(base: dict, market: list[dict], savings, today: date, base_path: Path) -> dict:
    """La banque ne garde que 90 j : passé FOLD_DAYS, l'épargne de plus de SETTLE_DAYS entre dans la base. Jamais sans
    lecture bancaire récente (`savings` None) : l'épargne absente sortirait du calcul pour de bon."""
    if savings is None or (today - date.fromisoformat(base["date"])).days <= FOLD_DAYS or any(a["missing"] for a in market):
        return base
    cut = (today - timedelta(days=SETTLE_DAYS)).isoformat()
    accounts = {}
    for a in market:
        b = base["accounts"].get(a["name"])
        if b:
            moved = _added(savings, a["name"], base["date"], cut)
            accounts[a["name"]] = {"value": b["value"] * _perf(a, b) + moved, "invested": b["invested"] + moved, "mkt": a["value"]}
    base = {"date": cut, "accounts": accounts}
    _write(base_path, base)
    return base


def view(path: Path = CSV, get=_get, clock=time.monotonic, savings=(), base_path: Path = BASE, today: date | None = None) -> dict | None:
    """None si aucun export importé. Valeur = base du propriétaire × variation des cours + épargne Trade Republic venue
    après (au prix versé) ; sans base, les positions du CSV tiennent lieu de base à la date de leur dernière opération."""
    if _cache["at"] is not None and clock() - _cache["at"] < TTL_S:
        return _cache["data"]
    if not Path(path).exists():
        return None
    market = _market(path, get)
    base = _load_base(base_path)
    if base:
        base = _fold(base, market, savings, today or date.today(), base_path)
    accounts = []
    for a in market:
        b = (base or {}).get("accounts", {}).get(a["name"])
        since = base["date"] if b else a["last"]
        b = b or {"value": a["value"], "invested": a["invested"], "mkt": a["value"]}
        new = _added(savings or [], a["name"], since)
        value, invested = b["value"] * _perf(a, b) + new, b["invested"] + new
        accounts.append(dict(a, value=round(value, 2), invested=round(invested, 2), gain=round(value - invested, 2),
                             pct=round((value / invested - 1) * 100, 2) if invested else None))
    data = {"accounts": accounts}
    _cache.update(at=clock(), data=data)
    return data
