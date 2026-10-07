"""Outils N0 de lecture : état du système, processus, recherche de fichiers (Windows, stdlib)."""
import csv
import ctypes
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from jarvis.core.router import fold
from jarvis.core.tools import Level, tool

SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
# Chemins absolus : pas de recherche dans le PATH, qu'un programme tiers pourrait détourner.
NVIDIA_SMI = SYSTEM32 / "nvidia-smi.exe"
TASKLIST = SYSTEM32 / "tasklist.exe"
GB = 1024 ** 3
MAX_PROCESSES = 50
MAX_RESULTS = 50
SEARCH_DEADLINE_S = 5.0
# Noms français des dossiers utilisateur -> nom réel sur le disque.
# ponytail: noms par défaut ; un dossier redirigé (OneDrive) exigera SHGetKnownFolderPath.
KNOWN_FOLDERS = {"documents": "Documents", "telechargements": "Downloads", "images": "Pictures",
                 "photos": "Pictures", "bureau": "Desktop", "musique": "Music", "videos": "Videos"}


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
        (n, ctypes.c_ulonglong) for n in (
            "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
            "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")
    ]


def _cpu_times() -> tuple[int, int]:
    idle, kernel, user = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    return idle.value, kernel.value + user.value  # le temps noyau inclut le temps d'inactivité


def _cpu_percent(interval: float = 0.2) -> float:
    idle1, total1 = _cpu_times()
    time.sleep(interval)
    idle2, total2 = _cpu_times()
    return round(100 * (1 - (idle2 - idle1) / max(total2 - total1, 1)), 1)


def _gpu() -> dict | None:
    """GPU NVIDIA via nvidia-smi ; None si absent ou illisible."""
    if not NVIDIA_SMI.is_file():
        return None
    try:
        out = subprocess.run(
            [str(NVIDIA_SMI), "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        name, util, used, total, temp = (v.strip() for v in out.splitlines()[0].split(","))
        return {"name": name, "percent": int(util), "vram_used_mb": int(used),
                "vram_total_mb": int(total), "temperature_c": int(temp)}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


@tool("system_status", "État du PC : CPU, RAM, disque système, GPU NVIDIA si présent.", Level.N0)
def system_status() -> dict:
    mem = _MemoryStatus(dwLength=ctypes.sizeof(_MemoryStatus))
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    disk = shutil.disk_usage(SYSTEM32.anchor)
    return {
        "cpu_percent": _cpu_percent(),
        "ram": {"total_gb": round(mem.ullTotalPhys / GB, 1),
                "used_gb": round((mem.ullTotalPhys - mem.ullAvailPhys) / GB, 1),
                "percent": mem.dwMemoryLoad},
        "disk": {"drive": SYSTEM32.anchor, "total_gb": round(disk.total / GB, 1),
                 "free_gb": round(disk.free / GB, 1), "percent": round(100 * disk.used / disk.total, 1)},
        "gpu": _gpu(),
    }


@tool("list_processes", f"Les {MAX_PROCESSES} processus qui utilisent le plus de mémoire.", Level.N0)
def list_processes() -> dict:
    out = subprocess.run([str(TASKLIST), "/fo", "csv", "/nh"], capture_output=True, timeout=10,
                         check=True, encoding="oem", errors="replace").stdout
    procs = [
        # Mémoire au format local (« 7 180 Ko », « 7,180 K ») : on ne garde que les chiffres.
        {"name": row[0], "pid": int(row[1]), "mem_mb": round(int(re.sub(r"\D", "", row[4]) or 0) / 1024, 1)}
        for row in csv.reader(out.splitlines()) if len(row) >= 5
    ]
    procs.sort(key=lambda p: p["mem_mb"], reverse=True)
    return {"total": len(procs), "processes": procs[:MAX_PROCESSES]}


@tool("search_files", f"Cherche les fichiers et dossiers dont le nom contient `name` sous `folder` "
                      f"({MAX_RESULTS} résultats max).", Level.N0, name=str, folder=str)
def search_files(name: str, folder: str) -> dict:
    needle = fold(name.strip())
    if not needle:
        raise ValueError("name ne doit pas être vide")
    folder = folder.strip()
    root = Path(KNOWN_FOLDERS.get(fold(folder), folder)).expanduser()
    if not root.is_absolute():
        root = Path.home() / root  # « documents » -> dossier Documents de l'utilisateur
    if not root.is_dir():
        raise ValueError(f"dossier introuvable : {folder}")
    found, deadline = [], time.monotonic() + SEARCH_DEADLINE_S
    for dirpath, dirnames, filenames in os.walk(root):  # ne suit pas les liens symboliques
        for entry in dirnames + filenames:
            if needle in fold(entry):
                found.append(str(Path(dirpath, entry)))
                if len(found) >= MAX_RESULTS:
                    return {"results": found, "complete": False}
        if time.monotonic() > deadline:
            return {"results": found, "complete": False}
    return {"results": found, "complete": True}
