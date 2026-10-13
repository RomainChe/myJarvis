"""Onglet Consommation de la PWA, étape 1 : énergie de la prise du PC (Tapo P110 via Home Assistant), N0, lecture seule.

Le Core échantillonne la puissance de la prise (`sample`, une fois par minute) et l'intègre en Wh par jour dans
`~/.jarvis/conso.db` (SQLite, une ligne par jour, 400 jours). Aucune courbe fine n'est gardée : un total quotidien révèle
bien moins les habitudes de vie qu'une courbe horaire (RGPD). Le Core éteint ou Home Assistant injoignable = un trou :
l'intervalle n'est pas compté et le temps réellement mesuré (`sec`) est conservé pour dire « mesuré sur N h ».
Prix du kWh : `~/.jarvis/conso.json` (`{"price_kwh": 0.25}`), saisi par le propriétaire, jamais lu depuis un contrat.
"""
import json
import math
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

HOME = Path.home() / ".jarvis"
DB = HOME / "conso.db"
CONFIG = HOME / "conso.json"
SAMPLE_S, MAX_GAP_S, KEEP_DAYS = 60, 180, 400
MAX_W, MAX_PRICE = 5000.0, 5.0  # multiprise 16 A = 3 680 W ; prix du kWh au-delà = saisie absurde
PERIODS = {"jour": 1, "semaine": 7, "mois": 30}  # fenêtres glissantes se terminant aujourd'hui
SCHEMA = "CREATE TABLE IF NOT EXISTS pc_energy (day TEXT PRIMARY KEY, wh REAL NOT NULL, sec REAL NOT NULL)"
_last: tuple[float, float] | None = None  # (instant, W) du dernier échantillon valide


def sample(watts: float, at: datetime | None = None, db: Path | None = None) -> None:
    """Ajoute l'énergie écoulée depuis l'échantillon précédent (trapèze). Mesure illisible ou trou trop long : rien."""
    global _last
    at, db = at or datetime.now(), db or DB
    t, prev, _last = at.timestamp(), _last, None
    if not (isinstance(watts, (int, float)) and math.isfinite(watts) and 0 <= watts <= MAX_W):
        return  # HA injoignable ou valeur absurde : l'intervalle suivant repart de zéro
    _last = (t, float(watts))
    if prev is None or not 0 < t - prev[0] <= MAX_GAP_S:
        return
    dt = t - prev[0]
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as cx, cx:
        cx.execute(SCHEMA)
        cx.execute("INSERT INTO pc_energy VALUES (?, ?, ?) ON CONFLICT(day) DO UPDATE "
                   "SET wh = wh + excluded.wh, sec = sec + excluded.sec",
                   (at.date().isoformat(), (prev[1] + watts) / 2 * dt / 3600, dt))
        cx.execute("DELETE FROM pc_energy WHERE day < ?", ((at.date() - timedelta(days=KEEP_DAYS)).isoformat(),))


def load_price(path: Path | None = None) -> float | None:
    """Prix du kWh en € ; absent ou hors bornes = None (les montants sont alors « indisponibles », jamais inventés)."""
    try:
        price = float(json.loads(Path(path or CONFIG).read_text(encoding="utf-8"))["price_kwh"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return price if 0 < price <= MAX_PRICE else None


def save_price(price: float, path: Path | None = None) -> None:
    if not (isinstance(price, (int, float)) and math.isfinite(price) and 0 < price <= MAX_PRICE):
        raise ValueError(f"prix du kWh entre 0 et {MAX_PRICE} €")
    path = Path(path or CONFIG)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"price_kwh": round(float(price), 4)}), encoding="utf-8")


def _window(cx, first: date, last: date) -> tuple[float, float, int]:
    return cx.execute("SELECT COALESCE(SUM(wh), 0), COALESCE(SUM(sec), 0), COUNT(*) FROM pc_energy WHERE day BETWEEN ? AND ?",
                      (first.isoformat(), last.isoformat())).fetchone()


def snapshot(db: Path | None = None, now: datetime | None = None, config: Path | None = None) -> dict:
    """kWh, € et période précédente pour jour / semaine / mois ; `kwh` None = aucune mesure sur la fenêtre."""
    now, db = now or datetime.now(), Path(db or DB)
    today, price = now.date(), load_price(config)
    out = {"configured": False, "price_kwh": price, "periods": {}, "series": [],
           "source": "Prise Tapo du PC, échantillonnée chaque minute (le Core éteint laisse un trou)"}
    empty = {"kwh": None, "eur": None, "prev_kwh": None, "hours": 0.0, "partial": False}
    out["periods"] = {name: dict(empty) for name in PERIODS}
    if not db.is_file():
        return out
    try:
        with closing(sqlite3.connect(db)) as cx:
            for name, n in PERIODS.items():
                wh, sec, rows = _window(cx, today - timedelta(days=n - 1), today)
                pwh, _, prows = _window(cx, today - timedelta(days=2 * n - 1), today - timedelta(days=n))
                if rows:
                    elapsed_h = (n - 1) * 24 + now.hour + now.minute / 60
                    out["periods"][name] = {
                        "kwh": round(wh / 1000, 3), "eur": None if price is None else round(wh / 1000 * price, 2),
                        "prev_kwh": round(pwh / 1000, 3) if prows else None, "hours": round(sec / 3600, 1),
                        "partial": sec / 3600 < 0.9 * elapsed_h}
            rows = cx.execute("SELECT day, wh FROM pc_energy WHERE day >= ? ORDER BY day",
                              ((today - timedelta(days=29)).isoformat(),)).fetchall()
    except sqlite3.Error:
        return out  # base absente de table ou illisible : « donnée indisponible »
    out["series"] = [{"day": d, "kwh": round(wh / 1000, 3)} for d, wh in rows]
    out["configured"] = bool(out["series"]) or any(p["kwh"] is not None for p in out["periods"].values())
    return out
