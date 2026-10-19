"""DriverWatch (projet voisin) : `driverwatch_accept` valide la proposition de la console, `driverwatch_update_all` met à jour
tous les pilotes en retard.

Rien n'est installé par Jarvis : les deux outils lancent `python -m driverwatch ...`, qui garde ses propres garde-fous
(point de restauration, signature, UAC). Le dossier du projet se règle par `JARVIS_DRIVERWATCH_DIR`.
"""
import os
import subprocess
import sys
from pathlib import Path

from jarvis.core.tools import Level, tool


def _dir() -> Path:
    path = Path(os.environ.get("JARVIS_DRIVERWATCH_DIR") or Path.home() / "Desktop" / "WebstormProject" / "driverwatch")
    if not (path / "driverwatch" / "__main__.py").is_file():
        raise FileNotFoundError("DriverWatch introuvable (variable JARVIS_DRIVERWATCH_DIR)")
    return path


def _spawn(command: str) -> None:
    subprocess.Popen([sys.executable, "-m", "driverwatch", command], cwd=_dir(), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


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
