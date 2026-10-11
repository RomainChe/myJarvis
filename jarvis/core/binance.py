"""Historique Binance en lecture seule (clé API « Enable Reading » uniquement), pour le prix de revient BTC/ETH.

Clé : `BINANCE_API_KEY` / `BINANCE_API_SECRET`, dans l'environnement ou dans le `.env` du dépôt (ignoré par git). Jamais
affichées ni journalisées. Sortie : `~/.jarvis/binance-history.json` (hors dépôt), lignes brutes de l'API par catégorie ;
une catégorie en échec est notée dans `errors` (code HTTP et message Binance) sans arrêter les autres. Aucune écriture
côté Binance : uniquement des GET signés.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.binance.com"
OUT = Path.home() / ".jarvis" / "binance-history.json"
DOTENV = Path(__file__).resolve().parents[2] / ".env"
START = datetime(2022, 1, 1, tzinfo=timezone.utc)
DAY_MS, WINDOW_DAYS, TIMEOUT, PAUSE_S = 86_400_000, 30, 15, 0.15
ASSETS = ("BTC", "ETH", "BNB", "SAND", "MANA", "USDT", "BUSD", "FDUSD", "USDC", "SXT")
QUOTES = ("EUR", "USDT", "BUSD", "FDUSD", "USDC", "BTC", "ETH")
SYMBOLS = tuple(a + q for a in ASSETS for q in QUOTES if a != q)  # paires inexistantes : « Invalid symbol », ignoré
# (nom, chemin, paramètres fixes, clé de liste dans la réponse | None si la réponse est la liste, fenêtre en jours, pause en s)
# fiat/orders pèse 90 000 sur un quota de 180 000/min : une seule fenêtre, une requête toutes les 30 s.
WINDOWED = (
    ("fiat_deposits", "/sapi/v1/fiat/orders", {"transactionType": 0, "rows": 500}, "data", 3650, 30),
    ("fiat_withdrawals", "/sapi/v1/fiat/orders", {"transactionType": 1, "rows": 500}, "data", 3650, 30),
    ("fiat_card_buys", "/sapi/v1/fiat/payments", {"transactionType": 0, "rows": 500}, "data", 3650, 30),
    ("convert", "/sapi/v1/convert/tradeFlow", {"limit": 1000}, "list", WINDOW_DAYS, PAUSE_S),
    ("auto_invest", "/sapi/v1/lending/auto-invest/history/list", {"size": 100}, "list", WINDOW_DAYS, PAUSE_S),
    ("earn_redemptions", "/sapi/v1/simple-earn/flexible/history/redemptionRecord", {"size": 100}, "rows", WINDOW_DAYS, PAUSE_S),
    ("crypto_deposits", "/sapi/v1/capital/deposit/hisrec", {"limit": 1000}, None, WINDOW_DAYS, PAUSE_S),
    ("withdrawals", "/sapi/v1/capital/withdraw/history", {"limit": 1000}, None, WINDOW_DAYS, PAUSE_S),
)
SNAPSHOTS = (
    ("spot_balances", "/api/v3/account", {}, "balances"),
    ("earn_flexible", "/sapi/v1/simple-earn/flexible/position", {"size": 100}, "rows"),
    ("earn_locked", "/sapi/v1/simple-earn/locked/position", {"size": 100}, "rows"),
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def load_keys(env=os.environ, dotenv: Path = DOTENV) -> tuple[str, str] | None:
    vals = {k: env.get(k, "").strip() for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET")}
    if not all(vals.values()):
        try:
            for line in Path(dotenv).read_text(encoding="utf-8").splitlines():
                k, _, v = line.partition("=")
                if k.strip() in vals and not vals[k.strip()]:
                    vals[k.strip()] = v.strip().strip("\"'")
        except OSError:
            pass
    return (vals["BINANCE_API_KEY"], vals["BINANCE_API_SECRET"]) if all(vals.values()) else None


def sign(query: str, secret: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _get(path: str, params: dict, keys: tuple[str, str]):
    query = urllib.parse.urlencode({**params, "recvWindow": 10_000, "timestamp": int(time.time() * 1000)})
    url = f"{BASE}{path}?{query}&signature={sign(query, keys[1])}"
    req = urllib.request.Request(url, headers={"X-MBX-APIKEY": keys[0], "User-Agent": "jarvis"})
    try:
        with _opener.open(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read(5_000_000))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read(2000)).get("msg", "")
        except (ValueError, OSError, AttributeError):
            msg = ""
        raise RuntimeError(f"HTTP {e.code} {msg}".strip()) from None


def windows(start_ms: int, end_ms: int, days: int = WINDOW_DAYS):
    step = days * DAY_MS
    for a in range(start_ms, end_ms, step):
        yield a, min(a + step - 1, end_ms)


def _rows(resp, key):
    rows = resp if key is None else (resp.get(key) if isinstance(resp, dict) else None)
    return rows if isinstance(rows, list) else []


def _call(get, path, params, keys, pause):
    for attempt in range(4):
        try:
            return get(path, params, keys)
        except RuntimeError as e:
            if not str(e).startswith("HTTP 429") or attempt == 3:
                raise
            pause(60)  # quota dépassé : on attend la minute suivante


def _err(e: Exception) -> str:
    return str(e) if isinstance(e, RuntimeError) else type(e).__name__


def fetch_all(keys, get=_get, now_ms: int | None = None, pause=time.sleep, only: set | None = None) -> dict:
    """`only` : noms de catégories à (re)lire, toutes si None ; `spot_trades` regroupe toutes les paires."""
    now_ms = now_ms or int(time.time() * 1000)
    want = lambda n: only is None or n in only
    data, errors = {}, {}
    for name, path, fixed, key, days, gap in WINDOWED:
        if not want(name):
            continue
        out = data[name] = []
        try:
            for a, b in windows(int(START.timestamp() * 1000), now_ms, days):
                page = 1
                while True:  # `current`/`page` ignorés par les endpoints sans pagination : arrêt quand la page est incomplète
                    resp = _call(get, path, {**fixed, "startTime": a, "endTime": b, "beginTime": a, "current": page, "page": page},
                                 keys, pause)
                    rows = _rows(resp, key)
                    out += rows
                    pause(gap)
                    size = fixed.get("size") or fixed.get("limit") or fixed.get("rows") or 0
                    if not size or len(rows) < size or page >= 50:
                        break
                    page += 1
        except Exception as e:  # RuntimeError (Binance), OSError (réseau), ValueError (JSON)
            errors[name] = _err(e)
    if want("spot_trades"):
        out = data["spot_trades"] = []
        for sym in SYMBOLS:
            last = 0
            try:
                while True:
                    rows = _rows(_call(get, "/api/v3/myTrades", {"symbol": sym, "fromId": last, "limit": 1000}, keys, pause), None)
                    out += [{**r, "symbol": sym} for r in rows]
                    pause(PAUSE_S)
                    if len(rows) < 1000:
                        break
                    last = rows[-1]["id"] + 1
            except Exception as e:
                if "Invalid symbol" not in str(e):
                    errors[f"spot_trades:{sym}"] = _err(e)
    for name, path, fixed, key in SNAPSHOTS:
        if not want(name):
            continue
        try:
            rows = _rows(_call(get, path, fixed, keys, pause), key)
            data[name] = [r for r in rows if name != "spot_balances" or float(r.get("free", 0)) + float(r.get("locked", 0)) > 0]
        except Exception as e:
            errors[name] = _err(e)
    return {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": data, "errors": errors}


def run(keys=None, get=_get, out: Path = OUT, only: set | None = None, pause=time.sleep) -> dict:
    """Relit les catégories demandées et les fusionne dans le fichier existant (les autres sont conservées)."""
    keys = keys or load_keys()
    if keys is None:
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET absents")
    result = fetch_all(keys, get, only=only, pause=pause)
    try:
        old = json.loads(Path(out).read_text(encoding="utf-8")).get("data", {})
    except (OSError, ValueError, AttributeError):
        old = {}
    result["data"] = {**old, **result["data"]}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
