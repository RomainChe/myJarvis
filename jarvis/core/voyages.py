"""Onglet Voyages de la PWA (Phase 6 point 10, étape 1, N0, lecture seule).

Lit `data/prices.csv` du clone local de flight-price-tracker (écrit chaque jour par son workflow GitHub). Dossier :
`~/.jarvis/voyages.json` (`{"dir": "..."}`), par défaut `~/Desktop/WebstormProject/flight-price-tracker`. Une recherche
= une colonne `search` du CSV ; changer de destination = nouvelle recherche, l'onglet suit donc la plus récente en tête.
Le contenu du CSV est une donnée : champs tronqués, prix numériques, liens https seulement. Pas d'audit : lecture N0.
Étape 2 : le workflow pousse sur GitHub, le clone local vieillit. `git fetch origin main` au plus une fois par heure (à
l'ouverture de l'onglet), puis lecture de `origin/main:data/prices.csv` par `git show` : ni checkout ni merge (la copie
de travail du propriétaire n'est jamais touchée), hooks désactivés. La lecture n'exécute aucun code du projet (seule la
validation de `voyage_destination`, étape 3, lance le `.venv` du tracker). Sans git : fichier local.
Phase 4 de hotel-price-tracker : `hotel_snapshot` lit de la même façon `historique/resume.json` (totaux déjà calculés par
le tracker : JARVIS ne recalcule rien). Dossier : clé `hotel_dir` du même `voyages.json`.
"""
import csv
import json
import os
import subprocess
import threading
import time
from datetime import date, datetime
from pathlib import Path

CONFIG = Path.home() / ".jarvis" / "voyages.json"
DEFAULT_DIR = Path.home() / "Desktop" / "WebstormProject" / "flight-price-tracker"
MAX_BYTES, MAX_SEARCHES, MAX_DAYS = 64 * 1024 * 1024, 10, 90
FETCH_EVERY_S, GIT_TIMEOUT_S = 3600, 20
GIT = ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]
_sync = {"at": 0.0, "ok": None, "error": None}  # dernière tentative de fetch (mémoire du processus)
_lock = threading.Lock()
TEXT = ("source", "origin", "dest", "return_from", "depart_date", "return_date", "airlines")
# Bon plan Japon : sous DEAL_BELOW €, escales dans la règle du tracker. Seules les lignes « Google Flights » comptent :
# avec des règles d'escales actives (config.yaml du tracker : max_stops, layover_hours) le tracker n'interroge que
# Google, dont l'attente à chaque escale est vérifiée ; le cache Aviasales ne la détaille pas (hors règle).
DEAL_BELOW, DEAL_MAX_STOPS, DEAL_SOURCE = 650, 2, "Google Flights"
JAPAN = {"NRT", "HND", "KIX", "ITM", "NGO", "FUK", "CTS", "OKA", "KMJ", "HIJ", "SDJ", "UKB"}
ALERT_STATE = Path.home() / ".jarvis" / "voyages-alert.json"
HOTEL_DEFAULT_DIR = Path.home() / "Desktop" / "WebstormProject" / "hotel-price-tracker"
MAX_RESUME_BYTES, MAX_STAGES = 64 * 1024, 10
_hotel_sync = {"at": 0.0, "ok": None, "error": None}


def tracker_dir(path: Path = CONFIG) -> Path:
    try:
        return Path(json.loads(Path(path).read_text(encoding="utf-8"))["dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_DIR


def hotel_dir(path: Path = CONFIG) -> Path:
    try:
        return Path(json.loads(Path(path).read_text(encoding="utf-8"))["hotel_dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return HOTEL_DEFAULT_DIR


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


def sync(root: Path, now: float | None = None, state: dict = _sync) -> dict:
    """`git fetch origin main` si la dernière tentative date de plus d'une heure ; renvoie l'état de la synchronisation."""
    now = time.time() if now is None else now
    with _lock:  # un seul fetch à la fois, les autres appels lisent l'état
        if now - state["at"] >= FETCH_EVERY_S and (root / ".git").is_dir():
            state["at"] = now
            try:
                _git(root, "fetch", "--quiet", "--no-tags", "origin", "main")
                state.update(ok=now, error=None)
            except (OSError, subprocess.SubprocessError):
                state["error"] = "échec de la synchronisation avec GitHub"  # détail non montré : chemins, URL
            if on_fetch:
                on_fetch(state["error"] is None)
        return {"synced_at": datetime.fromtimestamp(state["ok"]).isoformat(timespec="minutes") if state["ok"] else None,
                "sync_error": state["error"]}


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
        d = days.setdefault(name, {}).setdefault(day, {"best": o, "by_origin": {}, "deal": None})
        if (o["source"] == DEAL_SOURCE and o["dest"] in JAPAN and o["price"] < DEAL_BELOW
                and o["stops"] is not None and o["stops"] <= DEAL_MAX_STOPS
                and (d["deal"] is None or o["price"] < d["deal"]["price"])):
            d["deal"] = o
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
    # Bon plan : meilleur relevé vérifié du dernier jour de relevé seulement (un vieux relevé n'est plus une offre).
    latest = max((s["last_run"] for s in searches), default=None)
    deals = [{**days[s["name"]][latest]["deal"], "search": s["name"], "day": latest}
             for s in searches if s["last_run"] == latest and days[s["name"]][latest]["deal"]]
    deal = min(deals, key=lambda o: o["price"], default=None)
    return {"configured": True, "searches": searches[:MAX_SEARCHES], "deal": deal, **state}


def check_deal(notify, state: Path = ALERT_STATE, root: Path | None = None) -> dict | None:
    """Appelle `notify()` une fois par bon plan : nouvel itinéraire, ou même itinéraire devenu moins cher."""
    deal = snapshot(root).get("deal")
    if deal is None:
        return None
    key = f"{deal['origin']}>{deal['dest']} {deal['depart_date']}/{deal['return_date']}"
    try:
        last = json.loads(Path(state).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = {}
    if last.get("key") == key and deal["price"] >= last.get("price", 0):
        return None
    notify()
    Path(state).parent.mkdir(parents=True, exist_ok=True)
    Path(state).write_text(json.dumps({"key": key, "price": deal["price"]}), encoding="utf-8")
    return deal


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < 1_000_000 else None


def _text(v, n: int) -> str:
    """Texte d'une donnée externe, renvoyé au LLM : une seule ligne imprimable, tronquée."""
    return "".join(c for c in " ".join(str(v or "").split()) if c.isprintable())[:n]


def _day(v) -> str:
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        return ""


def _pick(o) -> dict | None:
    """Hôtel d'une étape ; tout champ illisible écarte l'hôtel plutôt que d'inventer un prix."""
    if not isinstance(o, dict) or any(_num(o.get(k)) is None for k in ("note10", "nuit", "total")):
        return None
    return {"hotel": _text(o.get("hotel"), 60), "note10": _num(o["note10"]), "nuit": _num(o["nuit"]), "total": _num(o["total"])}


def _read_resume(root: Path) -> bytes | None:
    if _hotel_sync["ok"]:
        try:
            return _git(root, "show", "origin/main:historique/resume.json")
        except (OSError, subprocess.SubprocessError):
            pass
    f = root / "historique" / "resume.json"
    if f.is_symlink() or not f.is_file() or f.stat().st_size > MAX_RESUME_BYTES:
        return None
    return f.read_bytes()


def hotel_snapshot(root: Path | None = None) -> dict:
    """Dernier relevé de hotel-price-tracker : totaux (hébergement + trajets), étapes. Le JSON est une donnée : champs bornés."""
    root = Path(root) if root else hotel_dir()
    state = sync(root, state=_hotel_sync)
    try:
        data = _read_resume(root)
        if not data or len(data) > MAX_RESUME_BYTES:
            raise ValueError
        raw = json.loads(data)
        stages = [{"ville": _text(e.get("ville"), 40), "chk_in": _day(e.get("chk_in")), "chk_out": _day(e.get("chk_out")),
                   "nuits": e["nuits"] if isinstance(e.get("nuits"), int) else None,
                   "recommande": _pick(e.get("recommande")), "moins_cher": _pick(e.get("moins_cher"))}
                  for e in raw["etapes"][:MAX_STAGES]]
        out = {"configured": True, "date": _day(raw["date"]), "devise": _text(raw.get("devise"), 3),
               "voyageurs": raw["voyageurs"] if isinstance(raw.get("voyageurs"), int) else None,
               "trajets": _num(raw.get("trajets")), "complet": raw.get("complet") is True, "etapes": stages,
               "total_recommande": _num(raw["total_recommande"]), "total_moins_cher": _num(raw["total_moins_cher"])}
        if out["total_recommande"] is None or out["total_moins_cher"] is None or len(out["date"]) != 10:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):  # json absent, invalide ou d'un autre schéma
        return {"configured": False, **state}
    return {**out, **state}
