"""Détection d'un jeu en cours (mode jeu : le LLM se décharge de la VRAM). Windows, stdlib."""
import os
import subprocess
from pathlib import Path

SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
POWERSHELL = SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe"
# Processus de la partie, pas les lanceurs (LeagueClient.exe, Riot Client, Epic restent ouverts toute la journée).
GAMES = {"league of legends.exe", "valorant-win64-shipping.exe", "genshinimpact.exe", "yuanshen.exe",
         "minecraft.windows.exe"}
EXTRA_FILE = Path(os.environ.get("JARVIS_GAMES") or Path.home() / ".jarvis" / "games.txt")


def steam_app_id() -> int:
    """Steam écrit l'identifiant du jeu lancé dans le registre (0 si aucun)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return int(winreg.QueryValueEx(k, "RunningAppID")[0])
    except (ImportError, OSError, ValueError):
        return 0


def process_names() -> set[str]:
    from jarvis.core.host import HAS_PC_TOOLS
    if not HAS_PC_TOOLS:  # Core sans PC : aucun jeu à détecter ici
        return set()
    from jarvis.tools.pc.system import all_processes  # import local : le cœur ne charge pas les outils au démarrage
    return {name.lower() for name, _ in all_processes()}


def javaw_commands() -> list[str]:
    """Lignes de commande des javaw.exe : Minecraft Java en est un, IntelliJ aussi."""
    ps = "(Get-CimInstance Win32_Process -Filter \"Name='javaw.exe'\").CommandLine"
    out = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, timeout=3, encoding="utf-8", errors="replace",
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return out.splitlines()


EXTRA_MAX = 64 * 1024  # un fichier plus gros est ignoré (lu à chaque phrase)


def extra_games() -> set[str]:
    if str(EXTRA_FILE).startswith("\\\\"):  # UNC : pas de lecture réseau à chaque phrase
        return set()
    try:
        with open(EXTRA_FILE, "rb") as f:
            raw = f.read(EXTRA_MAX + 1)  # lecture bornée : la taille peut changer entre un stat et la lecture
        if len(raw) > EXTRA_MAX:
            return set()
        return {line.strip().lower() for line in raw.decode("utf-8-sig").splitlines()
                if line.strip() and not line.startswith("#")}
    except (OSError, ValueError):  # fichier absent ou pas en UTF-8
        return set()


def is_gaming(names: set[str], steam_id: int = 0, javaw: list[str] = (), extra: set[str] = frozenset()) -> bool:
    if steam_id or names & (GAMES | extra):
        return True
    return any("minecraft" in cmd.lower() for cmd in javaw)


def detect() -> bool:
    """Échec ouvert côté jeu : si on ne peut pas lire les processus, on suppose qu'aucun jeu ne tourne."""
    try:
        names = process_names()
        javaw = javaw_commands() if "javaw.exe" in names else []
    except (OSError, subprocess.SubprocessError):
        return False
    return is_gaming(names, steam_app_id(), javaw, extra_games())
