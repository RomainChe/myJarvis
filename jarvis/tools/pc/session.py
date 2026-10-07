"""Session Windows : screen_off, lock_session, power, power_cancel (ctypes + shutdown.exe par chemin absolu)."""
import ctypes
import subprocess

from jarvis.core.tools import Level, tool
from jarvis.tools.pc.system import SYSTEM32

SHUTDOWN = SYSTEM32 / "shutdown.exe"
GRACE_S = 10  # délai avant arrêt/redémarrage : `shutdown /a` l'annule
ERROR_NO_SHUTDOWN = 1116  # « shutdown /a » sans arrêt en cours
POWER_ACTIONS = ("sleep", "restart", "shutdown")
HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF = 0xFFFF, 0x0112, 0xF170, 2


def _screen_off() -> None:
    # PostMessage : ne bloque pas si une fenêtre ne répond pas (SendMessage en diffusion le ferait).
    ctypes.windll.user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF)


def _lock() -> None:
    if not ctypes.windll.user32.LockWorkStation():
        raise OSError("verrouillage impossible")


def _suspend() -> None:
    # (hibernation=False, forcer=False, désactiver les réveils=False)
    if not ctypes.windll.powrprof.SetSuspendState(0, 0, 0):
        raise OSError("mise en veille impossible")


@tool("screen_off", "Éteint les écrans (le PC reste allumé ; un mouvement de souris les rallume).", Level.N1)
def screen_off() -> dict:
    _screen_off()
    return {"screen": "off"}


@tool("lock_session", "Verrouille la session Windows.", Level.N1)
def lock_session() -> dict:
    _lock()
    return {"locked": True}


@tool("power", f"Veille, redémarrage ou arrêt du PC (action : {', '.join(POWER_ACTIONS)}). "
               "Redémarrage et arrêt coupent Jarvis et Home Assistant.", Level.N2, action=str)
def power(action: str) -> dict:
    if action not in POWER_ACTIONS:
        raise ValueError(f"action inconnue : {action} (permises : {', '.join(POWER_ACTIONS)})")
    if action == "sleep":
        _suspend()
    else:  # liste d'arguments, sans /f : les applications peuvent demander d'enregistrer
        subprocess.run([str(SHUTDOWN), "/s" if action == "shutdown" else "/r", "/t", str(GRACE_S)],
                       check=True, capture_output=True, timeout=10)
    return {"power": action}


@tool("power_cancel", f"Annule un redémarrage ou un arrêt en attente (délai de {GRACE_S} s de `power`).", Level.N1)
def power_cancel() -> dict:
    done = subprocess.run([str(SHUTDOWN), "/a"], capture_output=True, timeout=10)
    if done.returncode == ERROR_NO_SHUTDOWN:  # rien en attente : le résultat voulu est atteint
        return {"power": "nothing_pending"}
    if done.returncode:
        raise OSError(f"annulation impossible (code {done.returncode})")
    return {"power": "cancelled"}
