"""Onglet Voyages de la PWA (Phase 6 point 10, étape 1, N0, lecture seule).

Lit `data/prices.csv` du clone local de flight-price-tracker (écrit chaque jour par son workflow GitHub). Dossier :
`~/.jarvis/voyages.json` (`{"dir": "..."}`), par défaut `~/Desktop/WebstormProject/flight-price-tracker`. Une recherche
= une colonne `search` du CSV ; changer de destination = nouvelle recherche, l'onglet suit donc la plus récente en tête.
Le contenu du CSV est une donnée : champs tronqués, prix numériques, liens https seulement. Pas d'audit : lecture N0.
"""
import csv
import json
from pathlib import Path

CONFIG = Path.home() / ".jarvis" / "voyages.json"
DEFAULT_DIR = Path.home() / "Desktop" / "WebstormProject" / "flight-price-tracker"
MAX_BYTES, MAX_SEARCHES, MAX_DAYS = 64 * 1024 * 1024, 10, 90
TEXT = ("source", "origin", "dest", "return_from", "depart_date", "return_date", "airlines")


def tracker_dir(path: Path = CONFIG) -> Path:
    try:
        return Path(json.loads(Path(path).read_text(encoding="utf-8"))["dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_DIR


def _offer(row: dict) -> dict | None:
    try:
        price = float(row["price"])
    except (TypeError, ValueError):
        return None
    if not 0 < price < 100_000:
        return None
    o = {k: str(row.get(k) or "")[:40] for k in TEXT}
    o["price"] = price
    o["stops"] = int(row["stops"]) if str(row.get("stops", "")).isdigit() else None
    o["duration_min"] = int(row["duration_min"]) if str(row.get("duration_min", "")).isdigit() else None
    link = row.get("link") or ""
    o["link"] = link[:2000] if link.startswith("https://") else None
    return o


def snapshot(root: Path | None = None) -> dict:
    f = (Path(root) if root else tracker_dir()) / "data" / "prices.csv"
    if f.is_symlink() or not f.is_file():
        return {"configured": False, "searches": []}
    # ponytail: relit tout le CSV à chaque ouverture de l'onglet (~90 Ko/jour), cache par mtime si ça devient lent
    days: dict[str, dict[str, dict]] = {}  # recherche -> jour -> {"best", "by_origin"}
    with f.open("rb") as h:
        header = h.readline(4096)
        size = f.stat().st_size
        if size > MAX_BYTES:  # garde les lignes les plus récentes, la première étant coupée
            h.seek(size - MAX_BYTES)
            h.readline()
        lines = (header + h.read(MAX_BYTES)).decode("utf-8", "replace").splitlines()
    for row in csv.DictReader(lines):
        name, day = str(row.get("search") or "")[:80], str(row.get("run_date") or "")[:10]
        o = _offer(row)
        if not name or len(day) != 10 or o is None:
            continue
        d = days.setdefault(name, {}).setdefault(day, {"best": o, "by_origin": {}})
        if o["price"] < d["best"]["price"]:
            d["best"] = o
        prev = d["by_origin"].get(o["origin"])
        if prev is None or o["price"] < prev["price"]:
            d["by_origin"][o["origin"]] = o
    searches = []
    for name, per_day in days.items():
        order = sorted(per_day)[-MAX_DAYS:]
        last = per_day[order[-1]]
        searches.append({
            "name": name,
            "last_run": order[-1],
            "best": last["best"],
            "previous": per_day[order[-2]]["best"]["price"] if len(order) > 1 else None,
            "lowest": min(per_day[d]["best"]["price"] for d in order),
            "history": [{"day": d, "price": per_day[d]["best"]["price"]} for d in order],
            "by_origin": sorted(last["by_origin"].values(), key=lambda o: o["price"]),
        })
    searches.sort(key=lambda s: (s["last_run"], -s["best"]["price"]), reverse=True)
    return {"configured": True, "searches": searches[:MAX_SEARCHES]}
