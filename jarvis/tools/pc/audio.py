"""Son : set_volume, mute (Core Audio via ctypes, sans dépendance) et media_control (touches multimédia)."""
import ctypes
import uuid
from contextlib import contextmanager
from ctypes import wintypes

from jarvis.core.tools import Level, tool

MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}  # VK_MEDIA_*
KEYEVENTF_KEYUP = 0x0002
CLSCTX_ALL = 23
_ole32 = ctypes.WinDLL("ole32")
_u32 = ctypes.WinDLL("user32")


class _Guid(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]


def _guid(text: str) -> _Guid:
    return _Guid.from_buffer_copy(uuid.UUID(text).bytes_le)


CLSID_ENUMERATOR = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_ENUMERATOR = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_ENDPOINT_VOLUME = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")


def _call(obj, index: int, *args, check: bool = True) -> None:
    """Appelle la méthode `index` de la table virtuelle COM de `obj` ; args = (type ctypes, valeur)."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *(t for t, _ in args))(vtable[index])
    if fn(obj, *(v for _, v in args)) < 0 and check:  # HRESULT négatif = échec (S_FALSE = 1 est un succès)
        raise OSError("périphérique audio indisponible")


@contextmanager
def _endpoint():
    """Interface IAudioEndpointVolume de la sortie par défaut."""
    initialized = _ole32.CoInitializeEx(None, 0) >= 0  # S_FALSE (déjà initialisé) compte aussi : à équilibrer
    enum, device, volume = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        if _ole32.CoCreateInstance(ctypes.byref(CLSID_ENUMERATOR), None, CLSCTX_ALL, ctypes.byref(IID_ENUMERATOR),
                                   ctypes.byref(enum)) < 0:
            raise OSError("périphérique audio indisponible")
        _call(enum, 4, (wintypes.DWORD, 0), (wintypes.DWORD, 1), (ctypes.c_void_p, ctypes.addressof(device)))
        _call(device, 3, (ctypes.c_void_p, ctypes.addressof(IID_ENDPOINT_VOLUME)), (wintypes.DWORD, CLSCTX_ALL),
              (ctypes.c_void_p, None), (ctypes.c_void_p, ctypes.addressof(volume)))
        yield volume
    finally:
        for com in (volume, device, enum):
            if com:
                _call(com, 2, check=False)  # Release renvoie un compteur, pas un HRESULT
        if initialized:
            _ole32.CoUninitialize()


def _set_volume(percent: int) -> None:
    with _endpoint() as volume:
        _call(volume, 7, (ctypes.c_float, percent / 100), (ctypes.c_void_p, None))
        if percent:
            _call(volume, 14, (wintypes.BOOL, 0), (ctypes.c_void_p, None))  # lever la sourdine en montant le son


def _set_mute(muted: bool) -> None:
    with _endpoint() as volume:
        _call(volume, 14, (wintypes.BOOL, int(muted)), (ctypes.c_void_p, None))


def _press(vk: int) -> None:
    _u32.keybd_event(vk, 0, 0, 0)
    _u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


@tool("set_volume", "Règle le volume principal du PC (0 à 100).", Level.N1, level=int)
def set_volume(level: int) -> dict:
    if not 0 <= level <= 100:
        raise ValueError("level doit être compris entre 0 et 100")
    _set_volume(level)
    return {"volume": level}


@tool("mute", "Coupe le son du PC (muted=true) ou le rétablit (muted=false).", Level.N1, muted=bool)
def mute(muted: bool) -> dict:
    _set_mute(muted)
    return {"muted": muted}


@tool("media_control", f"Commande multimédia : action parmi {', '.join(MEDIA_KEYS)}.", Level.N1, action=str)
def media_control(action: str) -> dict:
    if action not in MEDIA_KEYS:
        raise ValueError(f"action inconnue : {action} (permises : {', '.join(MEDIA_KEYS)})")
    _press(MEDIA_KEYS[action])
    return {"action": action}
