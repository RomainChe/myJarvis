"""Onglet Voyages de la PWA (Phase 6 point 10, étape 1, N0, lecture seule).

Lit `data/prices.csv` du clone local de flight-price-tracker (écrit chaque jour par son workflow GitHub). Dossier :
`~/.jarvis/voyages.json` (`{"dir": "..."}`), par défaut `~/Desktop/WebstormProject/flight-price-tracker`. Une recherche
= une colonne `search` du CSV ; changer de destination = nouvelle recherche, l'onglet suit donc la plus récente en tête.
Le contenu du CSV est une donnée : champs tronqués, prix numériques, liens https seulement. Pas d'audit : lecture N0.
Étape 2 : le workflow pousse sur GitHub, le clone local vieillit. `git fetch origin main` au plus une fois par heure (à
l'ouverture de l'onglet), puis lecture de `origin/main:data/prices.csv` par `git show` : ni checkout ni merge (la copie
de travail du propriétaire n'est jamais touchée), hooks désactivés. La lecture n'exécute aucun code du projet (seule la
validation de `voyage_destination`, étape 3, lance le `.venv` du tracker). Sans git : fichier local.
"""
import csv
import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

CONFIG = Path.home() / ".jarvis" / "voyages.json"
DEFAULT_DIR = Path.home() / "Desktop" / "WebstormProject" / "flight-price-tracker"
MAX_BYTES, MAX_SEARCHES, MAX_DAYS = 64 * 1024 * 1024, 10, 90
FETCH_EVERY_S, GIT_TIMEOUT_S = 3600, 20
GIT = ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]
_sync = {"at": 0.0, "ok": None, "error": None}  # dernière tentative de fetch (mémoire du processus)
_lock = threading.Lock()
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


def _git(root: Path, *args: str, input: bytes | None = None, env: dict | None = None, timeout: float = GIT_TIMEOUT_S) -> bytes:
    env = {**os.environ, **(env or {}), "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run([*GIT, "-C", str(root), *args], input=input, capture_output=True, check=True, timeout=timeout,
                          env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout


on_fetch = None  # rappel (ok: bool) après chaque `git fetch` tenté : branché sur le journal d'audit par le serveur


def sync(root: Path, now: float | None = None) -> dict:
    """`git fetch origin main` si la dernière tentative date de plus d'une heure ; renvoie l'état de la synchronisation."""
    now = time.time() if now is None else now
    with _lock:  # un seul fetch à la fois, les autres appels lisent l'état
        if now - _sync["at"] >= FETCH_EVERY_S and (root / ".git").is_dir():
            _sync["at"] = now
            try:
                _git(root, "fetch", "--quiet", "--no-tags", "origin", "main")
                _sync.update(ok=now, error=None)
            except (OSError, subprocess.SubprocessError):
                _sync["error"] = "échec de la synchronisation avec GitHub"  # détail non montré : chemins, URL
            if on_fetch:
                on_fetch(_sync["error"] is None)
        return {"synced_at": datetime.fromtimestamp(_sync["ok"]).isoformat(timespec="minutes") if _sync["ok"] else None,
                "sync_error": _sync["error"]}


def _read_csv(root: Path) -> bytes | None:
    """`origin/main:data/prices.csv` si le clone a été synchronisé, sinon le fichier de la copie de travail."""
    if _sync["ok"]:
        try:
            return _git(root, "show", "origin/main:data/prices.csv")
        except (OSError, subprocess.SubprocessError):
            pass
    f = root / "data" / "prices.csv"
    if f.is_symlink() or not f.is_file():
        return None
    with f.open("rb") as h:
        size = f.stat().st_size
        header = h.readline(4096)
        if size > MAX_BYTES:  # garde les lignes les plus récentes, la première étant coupée
            h.seek(size - MAX_BYTES)
            h.readline()
        return header + h.read(MAX_BYTES)


def _lines(data: bytes) -> list[str]:
    nl = data.find(b"\n") + 1
    if len(data) - nl > MAX_BYTES:  # sortie de `git show` : même coupe que pour le fichier
        tail = data[-MAX_BYTES:]
        data = data[:nl] + tail[tail.find(b"\n") + 1:]
    return data.decode("utf-8", "replace").splitlines()


def snapshot(root: Path | None = None) -> dict:
    root = Path(root) if root else tracker_dir()
    state = sync(root)
    data = _read_csv(root)
    if data is None:
        return {"configured": False, "searches": [], **state}
    # ponytail: relit tout le CSV à chaque ouverture de l'onglet (~90 Ko/jour), cache par mtime si ça devient lent
    days: dict[str, dict[str, dict]] = {}  # recherche -> jour -> {"best", "by_origin"}
    lines = _lines(data)
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
    return {"configured": True, "searches": searches[:MAX_SEARCHES], **state}
