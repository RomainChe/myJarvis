"""Supervision : `python -m jarvis doctor` (bilan) et `doctor --watch` (garde-fou lancé chaque minute).

`--watch` relance le Core s'il ne répond pas (2 essais à 5 s), journalise `core_restart` et envoie une
notification push, au plus une toutes les 30 min. Aucun contenu sensible : des noms de contrôle seulement.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

STATE = Path.home() / ".jarvis" / "watchdog.json"
TASK = "JARVIS - core"
UNIT = "jarvis-core.service"
GRACE_S = 90  # un Core relancé a ce temps pour écouter avant qu'on le relance encore
COOLDOWN_S = 30 * 60
DISK_MIN_GB = 5
ALERT = {"title": "Jarvis", "body": "Le Core s'était arrêté, il a été relancé."}
HEALTH_ALERT = {"title": "Jarvis", "body": "Journal d'audit rompu ou anormal : lance « python -m jarvis doctor »."}
HEALTH_EVERY_S = 3600
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
MODELS = Path(__file__).resolve().parents[2] / "models"


def backup_dir() -> Path:
    return Path(os.environ.get("JARVIS_BACKUP_DIR") or Path.home() / ".jarvis" / "backups")


def http_up(url: str, timeout: float = 5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:  # noqa: BLE001 (refus, délai, 4xx/5xx : le Core ne répond pas correctement)
        return False


def restart_task() -> None:
    if sys.platform != "win32":  # service systemd utilisateur (docs/MIGRATION_CORE_MINIPC.md lot 2)
        subprocess.run(["/usr/bin/systemctl", "--user", "restart", UNIT], check=False)
        return
    for action in ("/End", "/Run"):
        subprocess.run([str(SYSTEM32 / "schtasks.exe"), action, "/TN", TASK], cwd=SYSTEM32,
                       creationflags=0x08000000, check=False)


def _load(state: Path) -> dict:
    try:
        return json.loads(state.read_text())
    except (OSError, ValueError):
        return {}


def check_health(audit, notify_health, state: Path, now) -> None:
    """Contrôle la chaîne du journal au plus une fois par heure ; push (au plus un par 30 min) si elle est rompue."""
    s, t = _load(state), now()
    if t - s.get("health", 0) < HEALTH_EVERY_S:
        return
    s["health"] = t
    problems = audit.health()
    if problems and t - s.get("health_alert", 0) >= COOLDOWN_S:
        s["health_alert"] = t
        audit.log("watchdog", "audit_health", {}, None, "refusé", "; ".join(problems))
        try:
            notify_health()
        except Exception:  # noqa: BLE001 (le journal garde la trace même si le push échoue)
            pass
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(s))


def watch(audit, *, up, restart=restart_task, notify, state: Path = STATE, now=time.time, sleep=time.sleep,
          notify_health=None) -> str:
    """Renvoie « ok », « attente » (relancé il y a moins de GRACE_S) ou « relancé »."""
    if up() or (sleep(5), up())[1]:
        if notify_health is not None:
            check_health(audit, notify_health, state, now)
        return "ok"
    s, t = _load(state), now()
    if t - s.get("restart", 0) < GRACE_S:
        return "attente"
    restart()
    s["restart"] = t
    audit.log("watchdog", "core_restart", {}, None, "auto", "Core muet : tâche relancée")
    if t - s.get("alert", 0) >= COOLDOWN_S:
        s["alert"] = t
        try:
            notify()
        except Exception:  # noqa: BLE001 (le push est un confort : la relance a déjà eu lieu)
            pass
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(s))
    return "relancé"


def notify_all(audit_db_path: str, alert: dict = ALERT) -> None:
    from jarvis.core.devices import Devices
    from jarvis.core.push import Push, subject_from_env
    devices = Devices(audit_db_path)
    push = Push(devices, subject_from_env())
    for (dev,) in devices.db.execute("SELECT DISTINCT device_id FROM push_subs").fetchall():
        push.send(dev, alert)


def report(audit, port: int, backup_dir: Path, models: Path) -> list[tuple[str, str | None]]:
    """Un contrôle par ligne : (nom, problème ou None). Ne lève jamais."""
    from jarvis.core import ha, llm
    out: list[tuple[str, str | None]] = []

    def add(name, fn):
        try:
            out.append((name, fn()))
        except Exception as e:  # noqa: BLE001
            out.append((name, f"contrôle impossible ({type(e).__name__})"))

    add("core", lambda: None if http_up(f"http://127.0.0.1:{port}/") else f"ne répond pas sur 127.0.0.1:{port}")
    add("journal", lambda: "; ".join(audit.health()) or None)
    add("ollama", lambda: None if http_up(llm.OLLAMA + "/api/tags") else "Ollama injoignable")
    add("home assistant", lambda: (ha.version(), None)[1])
    add("sauvegarde", lambda: __import__("scripts.backup", fromlist=["check"]).check(backup_dir))
    add("disque", lambda: None if shutil.disk_usage(Path.home()).free >= DISK_MIN_GB * 2**30
        else f"moins de {DISK_MIN_GB} Go libres")

    def manifest():
        from jarvis.core.modelcheck import check_manifest
        bad = check_manifest(models / "MANIFEST.json", models) if (models / "MANIFEST.json").is_file() else []
        return f"{len(bad)} modèle(s) différent(s) du manifeste" if bad else None
    add("modèles", manifest)
    return out
