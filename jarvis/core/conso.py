"""Onglet Consommation de la PWA, étape 1 : énergie de la prise du PC (Tapo P110 via Home Assistant), N0, lecture seule.

Le Core échantillonne la puissance de la prise (`sample`, une fois par minute) et l'intègre en Wh par jour dans
`~/.jarvis/conso.db` (SQLite, une ligne par jour, 65 jours). Aucune courbe fine n'est gardée : un total quotidien révèle
bien moins les habitudes de vie qu'une courbe horaire (RGPD). Le Core éteint ou Home Assistant injoignable = un trou :
l'intervalle n'est pas compté et le temps réellement mesuré (`sec`) est conservé pour dire « mesuré sur N h ».
Prix du kWh : `~/.jarvis/conso.json` (`{"price_kwh": 0.25}`), saisi par le propriétaire, jamais lu depuis un contrat.
"""
import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

HOME = Path.home() / ".jarvis"
DB = HOME / "conso.db"
CONFIG = HOME / "conso.json"
SAMPLE_S, MAX_GAP_S, KEEP_DAYS = 60, 180, 65  # 65 j = les 30 jours + les 30 d'avant (minimisation RGPD)
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
        price = json.loads(Path(path or CONFIG).read_text(encoding="utf-8"))["price_kwh"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None  # `true` ne devient pas 1 €
    return price if 0 < price <= MAX_PRICE else None


def save_price(price: float, path: Path | None = None) -> None:
    if not (isinstance(price, (int, float)) and math.isfinite(price) and 0 < price <= MAX_PRICE):
        raise ValueError(f"prix du kWh entre 0 et {MAX_PRICE} €")
    path = Path(path or CONFIG)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")  # écriture atomique : un arrêt en cours ne laisse pas un fichier tronqué
    tmp.write_text(json.dumps({"price_kwh": round(float(price), 4)}), encoding="utf-8")
    os.replace(tmp, path)


def _window(cx, first: date, last: date) -> tuple[float, float, int]:
    return cx.execute("SELECT COALESCE(SUM(wh), 0), COALESCE(SUM(sec), 0), COUNT(*) FROM pc_energy WHERE day BETWEEN ? AND ?",
                      (first.isoformat(), last.isoformat())).fetchone()


def snapshot(db: Path | None = None, now: datetime | None = None, config: Path | None = None) -> dict:
    """kWh, € et période précédente pour jour / semaine / mois ; `kwh` None = aucune mesure sur la fenêtre."""
    now, db = now or datetime.now(), Path(db or DB)
    today, price = now.date(), load_price(config)
    out = {"configured": False, "price_kwh": price, "periods": {}, "series": [],
           "source": "Prise Tapo du PC, échantillonnée chaque minute (le Core éteint laisse un trou)"}
    empty = {"kwh": None, "eur": None, "prev_kwh": None, "hours": 0.0, "partial": False, "prev_hours": 0.0, "prev_partial": False}
    out["periods"] = {name: dict(empty) for name in PERIODS}
    if not db.is_file():
        return out
    try:
        with closing(sqlite3.connect(db)) as cx:
            for name, n in PERIODS.items():
                wh, sec, rows = _window(cx, today - timedelta(days=n - 1), today)
                pwh, psec, prows = _window(cx, today - timedelta(days=2 * n - 1), today - timedelta(days=n))
                if rows:
                    elapsed_h = (n - 1) * 24 + now.hour + now.minute / 60
                    out["periods"][name] = {
                        "kwh": round(wh / 1000, 3), "eur": None if price is None else round(wh / 1000 * price, 2),
                        "prev_kwh": round(pwh / 1000, 3) if prows else None, "hours": round(sec / 3600, 1),
                        "partial": sec / 3600 < 0.9 * elapsed_h,
                        "prev_hours": round(psec / 3600, 1), "prev_partial": bool(prows) and psec < 0.9 * n * 86400}
            rows = cx.execute("SELECT day, wh FROM pc_energy WHERE day >= ? ORDER BY day",
                              ((today - timedelta(days=29)).isoformat(),)).fetchall()
    except sqlite3.Error:
        return out  # base absente de table ou illisible : « donnée indisponible »
    by_day = dict(rows)  # axe calendaire : un jour sans mesure reste une barre vide (kwh None), il ne décale pas les autres
    days = [(today - timedelta(days=29 - i)).isoformat() for i in range(30)]
    out["series"] = [{"day": d, "kwh": round(by_day[d] / 1000, 3) if d in by_day else None} for d in days]
    out["configured"] = bool(by_day) or any(p["kwh"] is not None for p in out["periods"].values())
    return out


# --- Étape 2 : total du logement (compteur Linky via MyElectricalData, jours complets J-1 au plus récent) ---
HOME_SCHEMA = "CREATE TABLE IF NOT EXISTS home_energy (day TEXT PRIMARY KEY, kwh REAL NOT NULL, fetched_at TEXT NOT NULL)"


def store_home(days: dict[str, float], at: datetime | None = None, db: Path | None = None) -> None:
    """Remplace les jours reçus (un relevé corrigé par Enedis l'emporte) et purge au-delà de KEEP_DAYS."""
    at, db = at or datetime.now(), Path(db or DB)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as cx, cx:
        cx.execute(HOME_SCHEMA)
        cx.executemany("INSERT INTO home_energy VALUES (?, ?, ?) ON CONFLICT(day) DO UPDATE "
                       "SET kwh = excluded.kwh, fetched_at = excluded.fetched_at",
                       [(d, k, at.isoformat(timespec="seconds")) for d, k in days.items()])
        cx.execute("DELETE FROM home_energy WHERE day < ?", ((at.date() - timedelta(days=KEEP_DAYS)).isoformat(),))


def last_home_day(db: Path | None = None) -> str | None:
    db = Path(db or DB)
    if not db.is_file():
        return None
    try:
        with closing(sqlite3.connect(db)) as cx:
            return cx.execute("SELECT MAX(day) FROM home_energy").fetchone()[0]
    except sqlite3.Error:
        return None


def last_fetch(db: Path | None = None) -> datetime | None:
    db = Path(db or DB)
    if not db.is_file():
        return None  # sqlite3.connect créerait un fichier vide à la lecture
    try:
        with closing(sqlite3.connect(db)) as cx:
            v = cx.execute("SELECT MAX(fetched_at) FROM home_energy").fetchone()[0]
        return datetime.fromisoformat(v) if v else None
    except (sqlite3.Error, ValueError):
        return None


def home_snapshot(db: Path | None = None, now: datetime | None = None, config: Path | None = None) -> dict:
    """kWh, € et période précédente du logement ; fenêtres de jours complets finissant hier. `kwh` None = aucun relevé."""
    now, db = now or datetime.now(), Path(db or DB)
    last, price = now.date() - timedelta(days=1), load_price(config)
    empty = {"kwh": None, "eur": None, "prev_kwh": None, "days": 0, "partial": False, "pc_share": None,
             "prev_days": 0, "prev_partial": False, "pc_partial": False, "pc_days": 0, "pc_base_kwh": None,
             "pc_capped": False}
    out = {"configured": False, "price_kwh": price, "last_day": None, "fetched_at": None, "stale": False,
           "periods": {name: dict(empty) for name in PERIODS}, "series": [],
           "source": "Compteur Linky via MyElectricalData (relevé de la veille, quelques heures de décalage)"}
    if not db.is_file():
        return out
    iso = lambda d: d.isoformat()  # noqa: E731
    try:
        with closing(sqlite3.connect(db)) as cx:
            home = dict(cx.execute("SELECT day, kwh FROM home_energy WHERE day >= ?",
                                   (iso(last - timedelta(days=2 * 30 - 1)),)).fetchall())
            out["fetched_at"] = cx.execute("SELECT MAX(fetched_at) FROM home_energy").fetchone()[0]
            try:
                pc = {d: (k, s) for d, k, s in cx.execute("SELECT day, wh / 1000, sec FROM pc_energy WHERE day >= ?",
                                                          (iso(last - timedelta(days=29)),))}
            except sqlite3.Error:
                pc = {}  # pas encore de table de la prise : part du PC « indisponible »
    except sqlite3.Error:
        return out
    if not home:
        return out
    for name, n in PERIODS.items():
        days = [iso(last - timedelta(days=i)) for i in range(n)]
        got = [d for d in days if d in home]
        if not got:
            continue
        kwh = sum(home[d] for d in got)
        prev = [home[iso(last - timedelta(days=n + i))] for i in range(n) if iso(last - timedelta(days=n + i)) in home]
        both = [d for d in got if d in pc]  # la part du PC ne compare que des jours mesurés des deux côtés
        base = sum(home[d] for d in both)
        out["periods"][name] = {
            "kwh": round(kwh, 3), "eur": None if price is None else round(kwh * price, 2),
            "prev_kwh": round(sum(prev), 3) if prev else None, "days": len(got), "partial": len(got) < n,
            "prev_days": len(prev), "prev_partial": 0 < len(prev) < n,
            "pc_share": round(min(1.0, sum(pc[d][0] for d in both) / base), 3) if both and base > 0 else None,
            "pc_capped": bool(both) and base > 0 and sum(pc[d][0] for d in both) > base,  # PC > logement : relevés incohérents
            "pc_days": len(both), "pc_base_kwh": round(base, 3) if both else None,
            "pc_partial": any(pc[d][1] < 0.9 * 86400 for d in both)}  # le PC éteint = trou : la part est un minorant
    out["last_day"] = max(home)
    out["stale"] = out["last_day"] < iso(last)  # le dernier relevé n'est pas celui d'hier
    out["series"] = [{"day": d, "kwh": round(home[d], 3) if d in home else None}
                     for d in (iso(last - timedelta(days=29 - i)) for i in range(30))]
    out["configured"] = True
    return out
