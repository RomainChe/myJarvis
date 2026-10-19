"""Outils N0 de lecture : état du système, processus, recherche de fichiers (Windows, stdlib)."""
import ctypes
from ctypes import wintypes
import os
import re
import shutil
import subprocess
import time
from pathlib import Path, PureWindowsPath

from jarvis.core.dashboard import uptime_s
from jarvis.core.router import fold
from jarvis.core.tools import Level, tool

SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
# Chemins absolus : pas de recherche dans le PATH, qu'un programme tiers pourrait détourner.
NVIDIA_SMI = SYSTEM32 / "nvidia-smi.exe"
GB = 1024 ** 3
MAX_PROCESSES = 50
MAX_RESULTS = 50
SEARCH_DEADLINE_S = 5.0
# Noms français des dossiers utilisateur -> nom réel sur le disque.
# ponytail: noms par défaut ; un dossier redirigé (OneDrive) exigera SHGetKnownFolderPath.
KNOWN_FOLDERS = {"documents": "Documents", "telechargements": "Downloads", "images": "Pictures",
                 "photos": "Pictures", "bureau": "Desktop", "musique": "Music", "videos": "Videos"}
RESERVED_NAMES = {"con", "prn", "aux", "nul", "conin$", "conout$", "clock$",
                  *(f"{p}{i}" for p in ("com", "lpt") for i in [*range(1, 10), "¹", "²", "³"])}


def _allowed_root(folder: str) -> Path:
    """Dossier de recherche résolu, sous le dossier utilisateur ; refusé AVANT tout accès disque s'il est suspect."""
    folder = KNOWN_FOLDERS.get(fold(folder), folder).replace("/", "\\")
    # Lecteur autre que « X: » : UNC (\\hôte, \/hôte : fuite du hash NTLM), \\?\, \\.\.
    # « : » ailleurs qu'après la lettre de lecteur : flux ADS ; « C: » seul : relatif au lecteur.
    drive = PureWindowsPath(folder).drive
    if (drive and not re.fullmatch(r"[A-Za-z]:", drive)) or ":" in folder[2:] or re.fullmatch(r"[A-Za-z]:", folder):
        raise ValueError(f"chemin refusé : {folder}")
    if any(part.split(".")[0].strip().lower() in RESERVED_NAMES for part in folder.split("\\")):
        raise ValueError(f"nom réservé Windows : {folder}")
    # ponytail: seule racine autorisée = dossier utilisateur ; d'autres racines viendront d'un réglage N3.
    home = Path.home()
    root = Path(folder).expanduser()
    root = Path(os.path.abspath(root if root.is_absolute() else home / root))  # « .. » réduit sans accès disque
    if not root.is_relative_to(home):
        raise ValueError(f"hors du dossier utilisateur : {folder}")
    home = home.resolve()
    try:
        root = root.resolve(strict=True)  # suit liens et jonctions : on revérifie la racine ensuite
    except OSError:
        raise ValueError(f"dossier introuvable : {folder}") from None
    if not root.is_relative_to(home):
        raise ValueError(f"hors du dossier utilisateur : {folder}")
    return root


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
            capture_output=True, text=True, timeout=5, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        name, util, used, total, temp = (v.strip() for v in out.splitlines()[0].split(","))
        return {"name": name, "percent": int(util), "vram_used_mb": int(used),
                "vram_total_mb": int(total), "temperature_c": int(temp)}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


@tool("system_status", "État du PC : CPU, RAM, disque système, GPU NVIDIA si présent, durée depuis le démarrage.", Level.N0)
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
        "uptime_s": uptime_s(),  # le Core tourne sur le mini-PC : son propre uptime n'est pas celui du PC
    }


class _ProcEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


class _MemCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                       "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                       "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]


def _working_set_mb(k32, pid: int) -> float:
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return 0.0  # processus protégé : mémoire inconnue
    try:
        mem = _MemCounters(cb=ctypes.sizeof(_MemCounters))
        ok = k32.K32GetProcessMemoryInfo(handle, ctypes.byref(mem), mem.cb)
        return round(mem.WorkingSetSize / 1024 ** 2, 1) if ok else 0.0
    finally:
        k32.CloseHandle(handle)


def _kernel32():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcEntry)]
    return k32


def _snapshot(k32=None) -> list[tuple[str, int, int]]:
    """(nom d'image, pid, pid parent) de tous les processus, par l'API Windows directe (Toolhelp, ~10 ms)."""
    k32 = k32 or _kernel32()
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        raise OSError("liste des processus illisible")
    procs = []
    try:
        entry = _ProcEntry(dwSize=ctypes.sizeof(_ProcEntry))
        more = k32.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            procs.append((entry.szExeFile, entry.th32ProcessID, entry.th32ParentProcessID))
            more = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return procs


def all_processes(k32=None) -> list[tuple[str, int]]:
    """(nom d'image, pid) de tous les processus."""
    return [(name, pid) for name, pid, _ in _snapshot(k32)]


def ancestors(pid: int, k32=None) -> set[int]:
    """Parents, grands-parents… du processus `pid` (bornés : un PID réattribué peut former une boucle)."""
    parent = {p: pp for _, p, pp in _snapshot(k32)}
    found = set()
    while (pid := parent.get(pid, 0)) and pid not in found and len(found) < 64:
        found.add(pid)
    return found


@tool("game_running", "Un jeu est-il en cours sur le PC ? (mode jeu : le LLM évite la carte graphique)", Level.N0)
def game_running() -> bool:
    from jarvis.core import games  # import local : games importe tools.pc.system à l'usage
    return games.detect()


@tool("list_processes", f"Les {MAX_PROCESSES} processus qui utilisent le plus de mémoire.", Level.N0, external=True)
def list_processes() -> dict:
    k32 = _kernel32()
    procs = [{"name": name, "pid": pid, "mem_mb": _working_set_mb(k32, pid) if pid else 0.0}
             for name, pid in all_processes(k32)]
    procs.sort(key=lambda p: p["mem_mb"], reverse=True)
    return {"total": len(procs), "processes": procs[:MAX_PROCESSES]}


# R3 (Phase 5) : la marche tient chaque dossier OUVERT par handle, sans partage « suppression » : tant qu'un dossier est
# lu, il ne peut être ni renommé ni remplacé par une jonction. Chaque handle est vérifié (dossier réel, pas un point
# d'analyse, chemin final sous la racine) APRÈS l'ouverture, donc sans fenêtre entre vérification et lecture.
_ATTR_DIR, _ATTR_REPARSE = 0x10, 0x400
_NO_MORE_FILES = 18
_BUF = 64 * 1024


class _ByHandleInfo(ctypes.Structure):
    _fields_ = [("dwFileAttributes", wintypes.DWORD)] + [(f"_{i}", wintypes.DWORD) for i in range(12)]


def _k32_search():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleInfo)]
    k32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    k32.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    return k32


def _open_real_dir(k32, path: str, under: str | None) -> int | None:
    """Handle d'un vrai dossier (ni lien, ni jonction) situé sous `under`, ou None. À fermer par l'appelant."""
    # LIST_DIRECTORY | READ_ATTRIBUTES ; partage lecture+écriture mais pas suppression ; BACKUP_SEMANTICS | OPEN_REPARSE_POINT
    handle = k32.CreateFileW(path, 0x1 | 0x80, 0x3, None, 3, 0x02000000 | 0x00200000, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        return None
    ok = False
    try:
        info = _ByHandleInfo()
        buf = ctypes.create_unicode_buffer(32768)
        if not k32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            return None
        attrs = info.dwFileAttributes
        n = k32.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
        if not attrs & _ATTR_DIR or attrs & _ATTR_REPARSE or not 0 < n < len(buf):
            return None
        final = os.path.normcase(buf.value.removeprefix("\\\\?\\"))
        if under is not None and not (final == under or final.startswith(under.rstrip("\\") + "\\")):
            return None
        ok = True
        return handle
    finally:
        if not ok:
            k32.CloseHandle(handle)


def _entries(k32, handle):
    """(nom, attributs) des entrées d'un dossier ouvert, sans « . » ni « .. »."""
    buf = ctypes.create_string_buffer(_BUF)
    cls = 11  # FileIdBothDirectoryRestartInfo, puis FileIdBothDirectoryInfo (10)
    while k32.GetFileInformationByHandleEx(handle, cls, buf, _BUF):
        cls, off = 10, 0
        while True:
            nxt = int.from_bytes(buf.raw[off:off + 4], "little")
            attrs = int.from_bytes(buf.raw[off + 56:off + 60], "little")
            size = int.from_bytes(buf.raw[off + 60:off + 64], "little")
            name = buf.raw[off + 104:off + 104 + size].decode("utf-16-le")
            if name not in (".", ".."):
                yield name, attrs
            if not nxt:
                break
            off += nxt
    if ctypes.get_last_error() != _NO_MORE_FILES:
        raise OSError("dossier illisible")


@tool("search_files", f"Cherche les fichiers et dossiers dont le nom contient `name` sous `folder` "
                      f"({MAX_RESULTS} résultats max).", Level.N0, external=True, name=str, folder=str)
def search_files(name: str, folder: str) -> dict:
    needle = fold(name.strip())
    if not needle:
        raise ValueError("name ne doit pas être vide")
    root = _allowed_root(folder.strip())
    if not root.is_dir():
        raise ValueError(f"dossier introuvable : {folder}")
    k32 = _k32_search()
    home = os.path.normcase(str(Path.home().resolve()))
    found, deadline, open_handles = [], time.monotonic() + SEARCH_DEADLINE_S, []
    top = _open_real_dir(k32, str(root), home)  # la racine est revérifiée sur le handle : resolve() seul est une course
    if top is None:
        raise ValueError(f"dossier introuvable : {folder}")
    stack = [(top, root)]
    open_handles.append(top)
    try:
        while stack:
            handle, display = stack.pop()
            for entry, attrs in _entries(k32, handle):
                if time.monotonic() > deadline:  # un dossier géant ne bloque plus : l'échéance est testée par entrée
                    return {"results": found, "complete": False}
                if needle in fold(entry):
                    found.append(str(display / entry))
                    if len(found) >= MAX_RESULTS:
                        return {"results": found, "complete": False}
                if attrs & _ATTR_DIR and not attrs & _ATTR_REPARSE and entry.casefold() != ".jarvis":
                    child = _open_real_dir(k32, str(display / entry), home)
                    if child is not None:  # remplacé entre-temps par une jonction, ou inaccessible : ignoré
                        open_handles.append(child)
                        stack.append((child, display / entry))
            if time.monotonic() > deadline:
                return {"results": found, "complete": False}
        return {"results": found, "complete": True}
    finally:
        for h in open_handles:
            k32.CloseHandle(h)
