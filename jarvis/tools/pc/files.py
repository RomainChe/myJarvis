"""Fichiers : move_file et delete_file (corbeille). Chemins limités au dossier utilisateur par `_allowed_root`."""
import ctypes
import os
import shutil
from ctypes import wintypes
from pathlib import Path, PureWindowsPath

from jarvis.core.router import fold
from jarvis.core.tools import Level, tool
from jarvis.tools.pc.apps import CONFIG_DIR
from jarvis.tools.pc.system import KNOWN_FOLDERS, RESERVED_NAMES, _allowed_root

FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI, FOF_WANTNUKEWARNING = (
    3, 0x4, 0x10, 0x40, 0x400, 0x4000)
BAD_NAME_CHARS = set('<>:"|?*')  # « : » = flux ADS ; « * » et « ? » seraient des jokers pour SHFileOperation


class _FileOp(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", wintypes.WORD), ("aborted", wintypes.BOOL),
                ("mappings", ctypes.c_void_p), ("title", wintypes.LPCWSTR)]


def _recycle(path: Path) -> None:
    source = ctypes.create_unicode_buffer(str(path) + "\0")  # liste de chemins terminée par un double zéro
    # Pas de FOF_NOCONFIRMATION sans FOF_WANTNUKEWARNING : un fichier qui ne peut pas aller à la corbeille
    # (trop gros, disque amovible) provoque un avertissement au lieu d'une suppression définitive silencieuse.
    op = _FileOp(None, FO_DELETE, ctypes.cast(source, wintypes.LPCWSTR), None,
                 FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT | FOF_WANTNUKEWARNING, 0, None, None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.aborted:
        raise OSError(f"corbeille : échec (code {code:#x})")


def _protected() -> set[Path]:
    home = Path.home().resolve()
    return {home, *(home / name for name in set(KNOWN_FOLDERS.values()))}


def _existing(path: str) -> Path:
    """Fichier ou dossier existant, sous le dossier utilisateur, ni racine de dossier utilisateur ni ~/.jarvis."""
    resolved = _allowed_root(path.strip())
    _check_not_config(resolved)
    if resolved in _protected():
        raise ValueError(f"dossier utilisateur protégé : {path}")
    return resolved


def _check_not_config(path: Path) -> None:
    # ~/.jarvis porte le journal d'audit et les listes blanches : aucun outil de fichiers n'y touche.
    if path.is_relative_to(CONFIG_DIR.resolve()):
        raise ValueError("le dossier de configuration de Jarvis est protégé")


def _destination(dst: str, src: Path) -> Path:
    dst = dst.strip()
    try:
        folder = _allowed_root(dst)
    except ValueError:
        folder = None
    if folder is not None and folder.is_dir():  # dossier existant : on déplace dedans
        target = folder / src.name
    else:
        parts = PureWindowsPath(dst.replace("/", "\\"))
        name = parts.name
        if (not name or name in (".", "..") or BAD_NAME_CHARS & set(name) or name != name.rstrip(" .")
                or name.split(".")[0].strip().lower() in RESERVED_NAMES):
            raise ValueError(f"nom de destination refusé : {name or dst}")
        folder = _allowed_root(str(parts.parent))
        target = folder / name
    _check_not_config(folder)
    if os.path.lexists(target):
        raise ValueError(f"la destination existe déjà : {target.name}")
    if target.is_relative_to(src):
        raise ValueError("impossible de déplacer un dossier dans lui-même")
    return target


@tool("move_file", "Déplace ou renomme un fichier ou dossier du dossier utilisateur vers `dst` "
                   "(dossier existant, ou nouveau chemin) ; n'écrase jamais.", Level.N2, src=str, dst=str)
def move_file(src: str, dst: str) -> dict:
    source = _existing(src)
    target = _destination(dst, source)
    shutil.move(str(source), str(target))
    return {"moved": str(target)}


@tool("delete_file", "Envoie un fichier ou dossier du dossier utilisateur à la corbeille (récupérable).",
      Level.N2, path=str)
def delete_file(path: str) -> dict:
    target = _existing(path)
    _recycle(target)
    if os.path.lexists(target):
        raise OSError("le fichier n'a pas été supprimé")
    return {"recycled": str(target)}
