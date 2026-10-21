"""DriverWatch (projet voisin) : `driverwatch_accept` valide la proposition de la console, `driverwatch_update_all` met à jour
tous les pilotes en retard, `driverwatch_update_one` un seul (bouton de sa ligne), `pc_drivers` lit la dernière vérification
(onglet Pilotes).

Rien n'est installé par Jarvis : les outils lancent `python -m driverwatch ...`, qui garde ses propres garde-fous
(point de restauration, signature, UAC). Le dossier du projet se règle par `JARVIS_DRIVERWATCH_DIR`.
`status.json` (écrit par DriverWatch à chaque vérification) est une DONNÉE : bornée, validée, affichée en texte seul.
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from jarvis.core.tools import Level, tool


def _dir() -> Path:
    path = Path(os.environ.get("JARVIS_DRIVERWATCH_DIR") or Path.home() / "Desktop" / "WebstormProject" / "driverwatch")
    if not (path / "driverwatch" / "__main__.py").is_file():
        raise FileNotFoundError("DriverWatch introuvable (variable JARVIS_DRIVERWATCH_DIR)")
    return path


def _spawn(command: str, *args: str) -> None:
    subprocess.Popen([sys.executable, "-m", "driverwatch", command, *args], cwd=_dir(), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


STATUS = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DriverWatch" / "status.json"
STALE_S, RETRY_S, CHECK_S = 86400, 3600, 900  # relevé périmé après 1 j ; une relance par heure ; une vérification dure < 15 min
MAX_BYTES, MAX_DRIVERS = 64 * 1024, 60
STATUSES = ("critical", "moderate", "unknown", "ok")  # ordre d'affichage
FIELDS = {"id": 40, "name": 120, "category": 20, "installed": 40, "installed_date": 10, "latest": 40, "latest_date": 10,
          "source": 20}
_tried = {"at": 0.0}
_lock = threading.Lock()


def _driver(d) -> dict | None:
    if not isinstance(d, dict) or d.get("status") not in STATUSES:
        return None
    out = {k: str(d[k])[:n] if d.get(k) is not None else None for k, n in FIELDS.items()}
    out["days"] = d["days"] if type(d.get("days")) is int and 0 <= d["days"] < 100_000 else 0
    out.update(status=d["status"], newer=d.get("newer") is True, ignored=d.get("ignored") is True)
    return out


def _read(path: Path) -> tuple[datetime, list[dict]] | None:
    try:
        with path.open("rb") as f:
            raw = f.read(MAX_BYTES + 1)
        data = json.loads(raw.decode("utf-8")) if len(raw) <= MAX_BYTES else None
        at = datetime.fromisoformat(data["at"])
        rows = data["drivers"][:MAX_DRIVERS]
    except (OSError, ValueError, TypeError, KeyError, RecursionError):  # absent, illisible, trop gros ou trop imbriqué
        return None
    drivers = [d for d in map(_driver, rows) if d]
    drivers.sort(key=lambda d: (STATUSES.index(d["status"]), -d["days"]))
    return at, drivers


def status(path: Path | None = None, now: float | None = None, spawn=_spawn) -> dict:
    """Dernière vérification ; relance `driverwatch check` en tâche de fond si elle manque ou date de plus d'un jour."""
    now = time.time() if now is None else now
    try:
        _dir()
    except FileNotFoundError:
        return {"configured": False, "at": None, "drivers": [], "checking": False, "started": False}
    found = _read(path or STATUS)
    at = found[0].timestamp() if found else 0.0
    started = False
    with _lock:
        if now - at > STALE_S and now - _tried["at"] > RETRY_S:
            _tried["at"] = now
            try:
                spawn("check")  # lecture seule : NVIDIA et Windows Update, rien n'est installé
                started = True
            except OSError:  # Python introuvable, etc. : pas « en cours », nouvel essai plus tard
                _tried["at"] = now - CHECK_S
        checking = _tried["at"] > at and now - _tried["at"] < CHECK_S
    return {"configured": True, "at": found[0].isoformat(timespec="minutes") if found else None,
            "drivers": found[1] if found else [], "checking": checking, "started": started}


@tool("pc_drivers", "État des pilotes relevé par DriverWatch (onglet Pilotes).", Level.N0, owner_only=True)
def pc_drivers() -> dict:
    return status()


@tool("driverwatch_accept", "Accepte la mise à jour de pilotes proposée par DriverWatch au démarrage (Windows demandera"
                            " l'UAC).", Level.N1, taint_blocked=True)
def driverwatch_accept() -> dict:
    _spawn("accept")
    return {"driverwatch": "accepté"}


@tool("driverwatch_update_all", "Met à jour tous les pilotes en retard avec DriverWatch (point de restauration créé, "
                                "Windows demandera l'UAC).", Level.N2)
def driverwatch_update_all() -> dict:
    _spawn("update-all")
    return {"driverwatch": "mise à jour lancée"}


def _pending(driver_id: str) -> dict:
    """Pilote du dernier relevé ayant une version plus récente : l'id n'arrive jamais libre jusqu'à la commande."""
    found = _read(STATUS)
    for d in found[1] if found else ():
        if d["id"] == driver_id and d["newer"] and not d["ignored"] and not driver_id.startswith("-"):
            return d
    raise ValueError("pilote inconnu, ignoré ou déjà à jour dans le dernier relevé")


def _describe_one(driver_id: str) -> str:
    d = _pending(driver_id)
    return f"Mettre à jour {d['name']}" + (f" : {d['installed']} → {d['latest']}" if d["installed"] and d["latest"] else "")


@tool("driverwatch_update_one", "Met à jour un seul pilote en retard (id du dernier relevé DriverWatch ; point de "
                                "restauration créé, Windows demandera l'UAC).", Level.N2, describe=_describe_one, driver_id=str)
def driverwatch_update_one(driver_id: str) -> dict:
    _spawn("update", _pending(driver_id)["id"])
    return {"driverwatch": "mise à jour lancée"}
