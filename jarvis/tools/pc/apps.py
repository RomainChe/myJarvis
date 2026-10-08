"""Applications et processus : open_app, close_app, run_script (listes blanches), kill_process. Windows, ctypes."""
import ctypes
import json
import os
import re
import subprocess
from ctypes import wintypes
from pathlib import Path, PureWindowsPath

from jarvis.core.router import fold
from jarvis.core.tools import Level, tool
from jarvis.tools.pc.system import RESERVED_NAMES, SYSTEM32

CONFIG_DIR = Path.home() / ".jarvis"
APPS_FILE = CONFIG_DIR / "apps.json"  # {"navigateur": "C:\\...\\chrome.exe"} : nom -> exécutable, édité par le propriétaire
SCRIPTS_DIR = CONFIG_DIR / "scripts"  # seuls les scripts de ce dossier sont lançables
CONFIG_MAX = 64 * 1024
SCRIPT_NAME = re.compile(r"[A-Za-z0-9_-]+\.(ps1|bat|cmd)")
SCRIPT_TIMEOUT_S = 60
OUTPUT_MAX = 2000
CMD = SYSTEM32 / "cmd.exe"
POWERSHELL = SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe"
WINDOWS_DIR = Path(os.environ.get("SystemRoot", r"C:\Windows"))
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
PROCESS_TERMINATE, QUERY_LIMITED = 0x0001, 0x1000
WM_CLOSE = 0x0010
# S8 minimal (revue Phase 3) : le téléphone ne doit pas pouvoir couper sa propre liaison ni le LLM. Les processus
# de Hyper-V (vmwp, vmms) sont sous le dossier Windows, donc déjà refusés. Les ancêtres de Jarvis : Phase 5.
PROTECTED_IMAGES = {"tailscaled.exe", "tailscale.exe", "tailscale-ipn.exe"}
PROTECTED_PREFIXES = ("ollama",)  # ollama.exe, "ollama app.exe", ollama_llama_server.exe

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                            ctypes.POINTER(wintypes.DWORD)]
_u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_u32.EnumWindows.argtypes = [_ENUM_PROC, wintypes.LPARAM]
_u32.IsWindowVisible.argtypes = [wintypes.HWND]
_u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def _apps() -> dict[str, Path]:
    """Liste blanche nom -> exécutable. Le fichier est une donnée : chaque entrée est revalidée."""
    try:
        if APPS_FILE.stat().st_size > CONFIG_MAX:
            raise ValueError(f"{APPS_FILE.name} dépasse {CONFIG_MAX} octets")
        raw = json.loads(APPS_FILE.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ValueError(f"aucune application autorisée : {APPS_FILE} n'existe pas") from None
    except (OSError, ValueError) as e:
        raise ValueError(f"{APPS_FILE.name} illisible ({type(e).__name__})") from None
    apps = {}
    for key, value in (raw.items() if isinstance(raw, dict) else ()):
        path = PureWindowsPath(value) if isinstance(value, str) else None
        # Chemin absolu sur un lecteur local (« X:\ ») et un .exe : ni UNC, ni script, ni argument.
        if path and re.fullmatch(r"[A-Za-z]:\\", path.anchor) and path.suffix.lower() == ".exe":
            apps[fold(str(key).strip())] = Path(value)
    return apps


def _app(name: str) -> Path:
    apps = _apps()
    exe = apps.get(fold(name.strip()))
    if exe is None:
        raise ValueError(f"application non autorisée : {name} (autorisées : {', '.join(sorted(apps)) or 'aucune'})")
    if not exe.is_file():
        raise ValueError(f"exécutable introuvable pour {name}")
    return exe


def _image_of(handle) -> str:
    size = wintypes.DWORD(1024)
    buf = ctypes.create_unicode_buffer(size.value)
    if not _k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        raise OSError("processus illisible")
    return buf.value


def _image_of_pid(pid: int) -> str | None:
    handle = _k32.OpenProcess(QUERY_LIMITED, False, pid)
    if not handle:
        return None
    try:
        return _image_of(handle)
    except OSError:
        return None
    finally:
        _k32.CloseHandle(handle)


def _windows_of(exe: Path) -> list[int]:
    """Fenêtres de premier niveau visibles dont le processus est exactement cet exécutable."""
    found, target = [], os.path.normcase(str(exe))

    def visit(hwnd, _):
        pid = wintypes.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if _u32.IsWindowVisible(hwnd) and os.path.normcase(_image_of_pid(pid.value) or "") == target:
            found.append(hwnd)
        return True

    _u32.EnumWindows(_ENUM_PROC(visit), 0)
    return found


def _post_close(hwnd: int) -> None:
    _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


@tool("open_app", "Ouvre une application de la liste blanche (apps.json), par son nom.", Level.N1, name=str)
def open_app(name: str) -> dict:
    exe = _app(name)
    # Liste d'arguments, jamais de shell, jamais d'argument : l'application démarre seule.
    subprocess.Popen([str(exe)], cwd=exe.parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=DETACHED, close_fds=True)
    return {"opened": fold(name.strip())}


@tool("close_app", "Ferme proprement (demande de fermeture aux fenêtres) une application de la liste blanche.",
      Level.N1, name=str)
def close_app(name: str) -> dict:
    windows = _windows_of(_app(name))
    for hwnd in windows:
        _post_close(hwnd)
    return {"closed_windows": len(windows)}


@tool("run_script", "Lance un script (.ps1, .bat, .cmd) du dossier scripts, par son nom, sans argument.",
      Level.N2, private=True, external=True, name=str)
def run_script(name: str) -> dict:
    name = name.strip()
    if not SCRIPT_NAME.fullmatch(name) or name.split(".")[0].lower() in RESERVED_NAMES:
        raise ValueError("nom de script invalide : lettres, chiffres, - et _, extension .ps1, .bat ou .cmd")
    root = SCRIPTS_DIR.resolve()
    script = root / name
    # resolve() suit les liens : un lien vers l'extérieur du dossier est refusé.
    if not script.is_file() or script.resolve().parent != root:
        raise ValueError(f"script introuvable : {name}")
    if script.stat().st_nlink > 1:  # lien physique : le même fichier existe ailleurs, hors du dossier
        raise ValueError(f"script refusé (lien physique) : {name}")
    # Le script est désigné par son nom relatif au dossier ; l'interpréteur ne reçoit aucun autre argument.
    if script.suffix.lower() == ".ps1":
        cmd = [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", f".\\{name}"]
    else:
        cmd = [str(CMD), "/d", "/c", f".\\{name}"]
    done = subprocess.run(cmd, cwd=root, stdin=subprocess.DEVNULL, capture_output=True, timeout=SCRIPT_TIMEOUT_S,
                          encoding="oem", errors="replace")
    return {"exit_code": done.returncode, "output": (done.stdout + done.stderr)[:OUTPUT_MAX]}


def _check_target(image: str, name: str, pid: int) -> None:
    """Le processus visé est bien `name` (le PID a pu être réattribué) et n'appartient pas à Windows."""
    if PureWindowsPath(image).name.lower() != name.strip().lower():
        raise ValueError(f"le processus {pid} n'est pas {name}")
    if Path(image).is_relative_to(WINDOWS_DIR):
        raise ValueError(f"processus système protégé : {name}")
    real = PureWindowsPath(image).name.lower()
    if real in PROTECTED_IMAGES or real.startswith(PROTECTED_PREFIXES):
        raise ValueError(f"processus protégé (accès distant ou LLM de Jarvis) : {name}")


def _kill(pid: int, name: str) -> None:
    # Un seul handle pour vérifier puis terminer : le PID ne peut pas changer de propriétaire entre les deux.
    handle = _k32.OpenProcess(PROCESS_TERMINATE | QUERY_LIMITED, False, pid)
    if not handle:
        raise OSError(f"processus {pid} introuvable ou inaccessible")
    try:
        _check_target(_image_of(handle), name, pid)
        if not _k32.TerminateProcess(handle, 1):
            raise OSError(f"arrêt du processus {pid} impossible")
    finally:
        _k32.CloseHandle(handle)


@tool("kill_process", "Termine de force le processus `pid`, qui doit porter le nom `name` (ex. notepad.exe).",
      Level.N2, pid=int, name=str)
def kill_process(pid: int, name: str) -> dict:
    if pid <= 4 or pid > 0x7FFFFFFF or pid == os.getpid() or not name.strip():
        raise ValueError(f"pid ou nom refusé : {pid}")
    _kill(pid, name)
    return {"killed": pid, "name": name.strip()}
