"""Onglet Bien-être PC de la PWA (N0, lecture seule) : bilan de santé du PC du projet bien-etre-pc, relancé chaque jour.

Dossier : `~/.jarvis/bienetre.json` (`{"dir": "..."}`), par défaut `~/Desktop/WebstormProject/bien-etre-pc`. Le projet écrit
un fichier `historique/AAAA-MM-JJ_HHMMSS.json` par mesure ; l'onglet lit le plus récent. Si le dernier bilan n'est pas
d'aujourd'hui, `python -m bienetre` est relancé en tâche de fond (au plus une fois par heure, ni `--nettoyer` ni
`--html` : le projet ne supprime rien dans ce mode). Le contenu du JSON (noms de processus, de disques, de programmes)
est une DONNÉE : tronquée, jamais montrée au LLM, affichée en texte seul.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

CONFIG = Path.home() / ".jarvis" / "bienetre.json"
DEFAULT_DIR = Path.home() / "Desktop" / "WebstormProject" / "bien-etre-pc"
RUN_TIMEOUT_S, RETRY_S, MAX_BYTES, MAX_ITEMS = 180, 3600, 256 * 1024, 80
NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{6})\.json$")
STATUSES = {"problème": 0, "à surveiller": 1, "non mesuré": 2, "OK": 3}
FIELDS = {"composant": 60, "point": 60, "valeur": 300, "seuil": 200, "conseil": 500}
ENV_KEYS = ("SystemRoot", "SYSTEMROOT", "windir", "PATH", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA",
            "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "COMSPEC", "PSModulePath", "HOME")
_state = {"tried": 0.0, "error": None, "error_at": None, "running": False}
_lock = threading.Lock()
on_run = None  # rappel (ok: bool) après chaque relance : branché sur le journal d'audit par le serveur


def project_dir(path: Path = CONFIG) -> Path:
    try:
        d = Path(json.loads(Path(path).read_text(encoding="utf-8"))["dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_DIR
    return d if d.is_absolute() else DEFAULT_DIR


def _stamp(m: re.Match) -> datetime | None:
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M%S")
    except ValueError:  # 2026-13-45_996199.json : le nom ne décrit aucune date
        return None


def _files(root: Path) -> list[tuple[str, Path]]:
    """(jour, fichier) des bilans, du plus ancien au plus récent ; liens symboliques et noms inattendus écartés."""
    folder, out = root / "historique", []
    try:
        if not folder.resolve().is_relative_to(root.resolve()):  # jonction Windows vers un autre dossier
            return []
        for f in folder.iterdir():
            m = NAME.match(f.name)
            if m and _stamp(m) and f.is_file() and not f.is_symlink():
                out.append((m.group(1), f))
    except OSError:
        return []
    return sorted(out, key=lambda t: t[1].name)


def _load(f: Path) -> list[dict] | None:
    try:
        with f.open("rb") as h:
            raw = h.read(MAX_BYTES + 1)
        data = json.loads(raw.decode("utf-8-sig")) if len(raw) <= MAX_BYTES else None
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    items = []
    for c in data[:MAX_ITEMS]:
        if not isinstance(c, dict) or not isinstance(c.get("statut"), str) or c["statut"] not in STATUSES:
            continue
        item = {k: str(c.get(k) or "")[:n] for k, n in FIELDS.items()}
        item["statut"] = c["statut"]
        item["impact"] = c["impact"] if type(c.get("impact")) is int and c["impact"] in (1, 2, 3) else 1
        items.append(item)
    items.sort(key=lambda i: (STATUSES[i["statut"]], -i["impact"]))
    return items


def _counts(items: list[dict]) -> dict:
    return {s: sum(i["statut"] == s for i in items) for s in STATUSES}


def _python(root: Path) -> str:
    for rel in ("Scripts/python.exe", "bin/python"):
        p = root / ".venv" / rel
        if p.is_file():
            return str(p)
    return sys.executable


def run(root: Path) -> bool:
    env = {k: os.environ[k] for k in ENV_KEYS if k in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([_python(root), "-m", "bienetre"], cwd=root, env=env, timeout=RUN_TIMEOUT_S,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0


def _fail(error: str | None) -> None:
    """Garde le message et l'heure du premier échec d'une série (« en échec depuis »)."""
    if error is None or not _state["error"]:
        _state["error_at"] = datetime.now().isoformat(timespec="minutes") if error else None
    _state["error"] = error


def refresh_if_stale(root: Path | None = None, now: float | None = None, today: date | None = None, runner=run,
                     start=lambda f: threading.Thread(target=f, daemon=True).start()) -> bool:
    """Relance le bilan en tâche de fond si le dernier n'est pas d'aujourd'hui ; au plus un essai par heure."""
    root, now = Path(root) if root else project_dir(), time.time() if now is None else now
    if not (root / "bienetre").is_dir():
        return False
    files = _files(root)
    if files and files[-1][0] == (today or date.today()).isoformat():
        return False
    with _lock:
        if _state["running"] or now - _state["tried"] < RETRY_S:
            return False
        _state.update(running=True, tried=now)

    def job():
        ok = False
        try:
            ok = runner(root)
            _fail(None if ok else "le bilan a échoué")
        except Exception:  # noqa: BLE001 (OSError, délai dépassé, ou autre : l'onglet le dit, le serveur continue)
            _fail("le bilan n'a pas pu être lancé")
        finally:
            _state["running"] = False
            if on_run:
                on_run(ok)
    start(job)
    return True


def snapshot(root: Path | None = None) -> dict:
    root = Path(root) if root else project_dir()
    refresh_if_stale(root)
    files = _files(root)
    base = {"configured": (root / "bienetre").is_dir(), "running": _state["running"], "error": _state["error"], "error_at": _state["error_at"],
            "at": None, "items": [], "counts": None, "previous": None}
    for i in range(len(files) - 1, -1, -1):  # le plus récent lisible (un fichier abîmé n'efface pas l'onglet)
        items = _load(files[i][1])
        if items is None:
            continue
        m = NAME.match(files[i][1].name)
        base.update(at=_stamp(m).isoformat(timespec="minutes"),
                    items=items, counts=_counts(items))
        for day, f in reversed(files[:i]):  # point de comparaison : dernier bilan d'un jour précédent
            if day != m.group(1):
                prev = _load(f)
                if prev is not None:
                    base["previous"] = {"day": day, "counts": _counts(prev)}
                    break
        break
    return base
