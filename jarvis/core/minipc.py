"""Tuile « Mini-PC » du dashboard (N0, lecture seule, pas de ligne d'audit) : santé du serveur qui fait tourner le Core.

Contrôles = ceux de `doctor.report` (Core, journal, Ollama, Home Assistant, sauvegarde, disque, modèles). S'y ajoutent les
mises à jour en attente (`apt-get -s dist-upgrade`, simulation sans droits root), le redémarrage requis, la température, la
RAM, l'âge de la dernière sauvegarde et la dernière relance du Core par le garde-fou. Seuls des nombres et des noms de
contrôle sortent. Mesures Linux : sur un autre système le champ vaut None et la tuile l'omet.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from jarvis.core import doctor
from jarvis.core.dashboard import uptime_s

APT = "/usr/bin/apt-get"
REBOOT_FLAG = Path("/var/run/reboot-required")
THERMAL = "/sys/class/thermal/thermal_zone*/temp"
STATUS_TTL_S, APT_TTL_S, RESTART_SHOWN_S = 60, 3600, 7 * 86400
_cache: dict[str, tuple[float, object]] = {}
_locks: dict[str, threading.Lock] = {}  # un verrou par mesure : apt (30 s) ne bloque pas la lecture de la RAM
_guard = threading.Lock()


def _memo(key: str, ttl: int, fn, clock=time.monotonic):
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        hit = _cache.get(key)
        if hit and clock() - hit[0] < ttl:
            return hit[1]
        try:
            value = fn()
        except Exception:  # noqa: BLE001 (mesure indisponible : champ absent, jamais d'erreur vers l'écran)
            value = None
        _cache[key] = (clock(), value)
        return value


def parse_apt(out: str) -> dict:
    """Lignes « Inst … » de la simulation : paquets à mettre à jour, dont ceux d'un dépôt « -security »."""
    inst = [line for line in out.splitlines() if line.startswith("Inst ")]
    return {"count": len(inst), "security": sum("-security" in line for line in inst)}


def _apt() -> dict | None:
    if not os.path.exists(APT):
        return None
    done = subprocess.run([APT, "-s", "dist-upgrade"], capture_output=True, text=True, timeout=30, check=True,
                          env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
    return parse_apt(done.stdout)


def ram_pct(meminfo: str) -> int | None:
    kb = {k: int(v.split()[0]) for k, _, v in (line.partition(":") for line in meminfo.splitlines()) if v.strip()}
    return round(100 - 100 * kb["MemAvailable"] / kb["MemTotal"]) if kb.get("MemTotal") else None


def _temp_c() -> float | None:
    from glob import glob
    temps = [int(Path(p).read_text()) / 1000 for p in glob(THERMAL)]
    return round(max(temps), 1) if temps else None


def _backup_age_h(backup_dir: Path) -> int | None:
    from scripts import backup
    copy = backup.latest(backup_dir)
    return round((time.time() - copy.stat().st_mtime) / 3600) if copy else None


def _restart_at(state: Path = doctor.STATE, now=time.time) -> float | None:
    at = doctor._load(state).get("restart")
    return at if isinstance(at, (int, float)) and 0 < now() - at < RESTART_SHOWN_S else None


def status(audit, port: int, backup_dir: Path | None = None) -> dict:
    backup_dir = backup_dir or doctor.backup_dir()

    def checks():
        home = str(Path.home())
        return [{"name": n, "problem": p.replace(home, "~")[:160]} for n, p in doctor.report(audit, port, backup_dir, doctor.MODELS) if p]

    linux = sys.platform != "win32"
    disk = shutil.disk_usage(Path.home())
    return {
        "problems": _memo("checks", STATUS_TTL_S, checks) or [],
        "updates": _memo("apt", APT_TTL_S, _apt) if linux else None,
        "reboot": REBOOT_FLAG.exists() if linux else None,
        "disk_free_gb": round(disk.free / 2**30), "disk_total_gb": round(disk.total / 2**30),
        "temp_c": _memo("temp", STATUS_TTL_S, _temp_c) if linux else None,
        "ram_pct": _memo("ram", STATUS_TTL_S, lambda: ram_pct(Path("/proc/meminfo").read_text())) if linux else None,
        "backup_age_h": _memo("backup", STATUS_TTL_S, lambda: _backup_age_h(backup_dir)),
        "uptime_s": uptime_s(),
        "restart_at": _restart_at(),
    }
