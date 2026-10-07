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
DRIVE_FIXED = 3
RECYCLE_MAX_BYTES = 1 << 30  # au-delà, la corbeille risque de refuser : pas de suppression définitive silencieuse
RECYCLE_MAX_ENTRIES = 50_000
_shell32 = ctypes.WinDLL("shell32")
_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
BAD_NAME_CHARS = set('<>:"|?*')  # « : » = flux ADS ; « * » et « ? » seraient des jokers pour SHFileOperation


class _FileOp(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", wintypes.WORD), ("aborted", wintypes.BOOL),
                ("mappings", ctypes.c_void_p), ("title", wintypes.LPCWSTR)]


def _drive_type(path: Path) -> int:
    return _kernel32.GetDriveTypeW(path.anchor)


def _too_big(path: Path) -> bool:
    """Taille cumulée au-dessus de la limite (ou trop d'entrées) ; les jonctions ne sont pas suivies."""
    if path.is_file():
        return path.stat().st_size > RECYCLE_MAX_BYTES
    total = entries = 0
    for folder, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if not os.path.isjunction(os.path.join(folder, d))]
        for name in names:
            entries += 1
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
            if total > RECYCLE_MAX_BYTES or entries > RECYCLE_MAX_ENTRIES:
                return True
    return False


def _recycle(path: Path) -> None:
    # SHFileOperation ne sait pas refuser seul : sans FOF_WANTNUKEWARNING un fichier non recyclable est supprimé
    # définitivement, avec lui il peut afficher une boîte qui bloque le Core. On écarte donc d'avance les cas
    # qui échouent (lecteur amovible ou réseau, taille au-dessus de la limite) et on n'envoie que des flags sans UI.
    if _drive_type(path) != DRIVE_FIXED:
        raise ValueError("la corbeille n'est disponible que sur un disque fixe")
    if _too_big(path):
        raise ValueError("trop volumineux pour la corbeille : à supprimer à la main")
    source = ctypes.create_unicode_buffer(str(path) + "\0")  # liste de chemins terminée par un double zéro
    op = _FileOp(None, FO_DELETE, ctypes.cast(source, wintypes.LPCWSTR), None,
                 FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT, 0, None, None)
    code = _shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.aborted:
        raise OSError(f"corbeille : échec (code {code:#x})")


def _protected() -> set[Path]:
    home = Path.home().resolve()
    return {home, *(home / name for name in set(KNOWN_FOLDERS.values()))}


# Persistance ou destruction : jamais touchés, en source comme en destination (S7).
SENSITIVE_NAMES = {"appdata", ".ssh", ".gnupg", ".git"}


def _check_sensitive(path: Path) -> None:
    parts = {p.casefold() for p in path.relative_to(Path.home().resolve()).parts}
    if parts & SENSITIVE_NAMES or {"start menu", "startup"} <= parts:
        raise ValueError("dossier sensible protégé (AppData, .ssh, .gnupg, .git, Démarrage)")


def _existing(path: str) -> Path:
    """Fichier ou dossier existant, sous le dossier utilisateur, ni racine de dossier utilisateur ni ~/.jarvis."""
    resolved = _allowed_root(path.strip())
    _check_not_config(resolved)
    _check_sensitive(resolved)
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
    _check_sensitive(target)
    if os.path.lexists(target):
        raise ValueError(f"la destination existe déjà : {target.name}")
    if target.is_relative_to(src):
        raise ValueError("impossible de déplacer un dossier dans lui-même")
    return target


def _describe_move(src: str, dst: str) -> str:
    source = _existing(src)
    return f"{source} -> {_destination(dst, source)}"


@tool("move_file", "Déplace ou renomme un fichier ou dossier du dossier utilisateur vers `dst` "
                   "(dossier existant, ou nouveau chemin) ; n'écrase jamais.", Level.N2, describe=_describe_move, src=str, dst=str)
def move_file(src: str, dst: str) -> dict:
    source = _existing(src)
    target = _destination(dst, source)
    shutil.move(str(source), str(target))
    return {"moved": str(target)}


def _describe_delete(path: str) -> str:
    return f"corbeille : {_existing(path)}"


@tool("delete_file", "Envoie un fichier ou dossier du dossier utilisateur à la corbeille (récupérable).",
      Level.N2, describe=_describe_delete, path=str)
def delete_file(path: str) -> dict:
    target = _existing(path)
    _recycle(target)
    if os.path.lexists(target):
        raise OSError("le fichier n'a pas été supprimé")
    return {"recycled": str(target)}
