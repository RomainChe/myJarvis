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

FOF_SILENT, FOF_NOCONFIRMATION, FOF_NOERRORUI, FOFX_RECYCLEONDELETE = 0x4, 0x10, 0x400, 0x80000
DRIVE_FIXED = 3
_ole32 = ctypes.WinDLL("ole32")
_shell32 = ctypes.WinDLL("shell32")
_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
_ole32.CoInitializeEx.restype = ctypes.c_long  # S_FALSE (1) est un succès à équilibrer ; on teste à la main
BAD_NAME_CHARS = set('<>:"|?*')  # « : » = flux ADS ; « * » et « ? » : jokers
CLSID_FILE_OPERATION = "{3AD05575-8857-4850-9277-11B85BDB8E09}"
IID_FILE_OPERATION = "{947AAB5F-0A5C-4C13-B4D6-4BF7836FC9F8}"
IID_SHELL_ITEM = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
RPC_E_CHANGED_MODE = -2147417850  # 0x80010106 : COM déjà initialisé autrement sur ce thread, rien à défaire
_RELEASE, _SET_FLAGS, _DELETE_ITEM, _PERFORM, _ABORTED = 2, 5, 18, 21, 22  # index vtable (IUnknown puis IFileOperation)


class _Guid(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _Guid:
    guid = _Guid()
    _ole32.CLSIDFromString(text, ctypes.byref(guid))
    return guid


def _com(obj, index: int, *args):
    """Appelle la méthode `index` de la vtable COM `obj` ; args = [(type, valeur), ...] ; HRESULT d'échec -> OSError."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_ulong if index == _RELEASE else ctypes.HRESULT, ctypes.c_void_p, *(t for t, _ in args))
    return proto(vtable[index])(obj, *(v for _, v in args))


def _drive_type(path: Path) -> int:
    return _kernel32.GetDriveTypeW(path.anchor)


def _recycle(path: Path) -> None:
    """Corbeille via IFileOperation + FOFX_RECYCLEONDELETE : si l'élément ne peut pas être recyclé (corbeille
    désactivée pour le lecteur, quota dépassé), l'opération ÉCHOUE au lieu de supprimer définitivement
    (SHFileOperation/FOF_ALLOWUNDO supprimait alors sans erreur). Aucune boîte de dialogue."""
    if _drive_type(path) != DRIVE_FIXED:
        raise ValueError("la corbeille n'est disponible que sur un disque fixe")
    hr = _ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    if hr < 0 and hr != RPC_E_CHANGED_MODE:
        raise OSError(f"corbeille : COM indisponible ({hr & 0xFFFFFFFF:#x})")
    release = []  # objets COM à relâcher, dans l'ordre inverse de création
    try:
        op, item = ctypes.c_void_p(), ctypes.c_void_p()
        if _ole32.CoCreateInstance(ctypes.byref(_guid(CLSID_FILE_OPERATION)), None, 0x17,
                                   ctypes.byref(_guid(IID_FILE_OPERATION)), ctypes.byref(op)) < 0:
            raise OSError("corbeille : IFileOperation indisponible")
        release.append(op)
        if _shell32.SHCreateItemFromParsingName(str(path), None, ctypes.byref(_guid(IID_SHELL_ITEM)),
                                                ctypes.byref(item)) < 0:
            raise OSError("corbeille : élément introuvable")
        release.append(item)
        _com(op, _SET_FLAGS, (wintypes.DWORD, FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOFX_RECYCLEONDELETE))
        _com(op, _DELETE_ITEM, (ctypes.c_void_p, item), (ctypes.c_void_p, None))
        _com(op, _PERFORM)
        aborted = wintypes.BOOL()
        _com(op, _ABORTED, (ctypes.POINTER(wintypes.BOOL), ctypes.byref(aborted)))
        if aborted.value:
            raise OSError("corbeille : refusée (désactivée ou pleine), rien n'a été supprimé")
    finally:
        for obj in reversed(release):
            _com(obj, _RELEASE)
        if hr >= 0:
            _ole32.CoUninitialize()


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
