"""screenshot : capture de tout le bureau virtuel en PNG (GDI via ctypes, PNG par zlib), sans dépendance."""
import ctypes
import struct
import zlib
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from jarvis.core.tools import Level, tool

SHOT_DIR = Path.home() / "Pictures" / "Jarvis"
SRCCOPY_CAPTUREBLT = 0x00CC0020 | 0x40000000
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
MAX_PIXELS = 16384 * 8192  # borne de mémoire : 4 octets par pixel
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_g32 = ctypes.WinDLL("gdi32", use_last_error=True)
for _fn, _res, _args in (
        (_u32.GetDC, wintypes.HDC, [wintypes.HWND]), (_u32.ReleaseDC, ctypes.c_int, [wintypes.HWND, wintypes.HDC]),
        (_g32.CreateCompatibleDC, wintypes.HDC, [wintypes.HDC]),
        (_g32.CreateCompatibleBitmap, wintypes.HBITMAP, [wintypes.HDC, ctypes.c_int, ctypes.c_int]),
        (_g32.SelectObject, wintypes.HGDIOBJ, [wintypes.HDC, wintypes.HGDIOBJ]),
        (_g32.GetDIBits, ctypes.c_int, [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                        ctypes.c_void_p, wintypes.UINT]),
        (_g32.DeleteObject, wintypes.BOOL, [wintypes.HGDIOBJ]), (_g32.DeleteDC, wintypes.BOOL, [wintypes.HDC]),
        (_g32.BitBlt, wintypes.BOOL, [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC] + [ctypes.c_int] * 2
         + [wintypes.DWORD])):
    _fn.restype, _fn.argtypes = _res, _args


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def _capture() -> tuple[int, int, bytes]:
    """(largeur, hauteur, pixels BGRA de haut en bas) de tous les écrans."""
    _u32.SetProcessDPIAware()  # sinon les tailles sont celles d'un écran « virtualisé »
    x, y, w, h = (_u32.GetSystemMetrics(m) for m in (SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN,
                                                    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN))
    if not (0 < w * h <= MAX_PIXELS):
        raise OSError("taille d'écran inattendue")
    screen = _u32.GetDC(None)
    memory = _g32.CreateCompatibleDC(screen)
    bitmap = _g32.CreateCompatibleBitmap(screen, w, h)
    try:
        if not (screen and memory and bitmap):
            raise OSError("capture impossible")
        _g32.SelectObject(memory, bitmap)
        if not _g32.BitBlt(memory, 0, 0, w, h, screen, x, y, SRCCOPY_CAPTUREBLT):
            raise OSError("capture impossible")
        header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), w, -h, 1, 32, 0)  # hauteur < 0 : haut en bas
        pixels = ctypes.create_string_buffer(w * h * 4)
        if not _g32.GetDIBits(memory, bitmap, 0, h, pixels, ctypes.byref(header), 0):
            raise OSError("capture impossible")
        return w, h, pixels.raw
    finally:
        if bitmap:
            _g32.DeleteObject(bitmap)
        if memory:
            _g32.DeleteDC(memory)
        if screen:
            _u32.ReleaseDC(None, screen)


def _png(w: int, h: int, bgra: bytes) -> bytes:
    rgb = bytearray(w * h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    stride = w * 3
    raw = b"".join(b"\0" + bytes(rgb[i:i + stride]) for i in range(0, len(rgb), stride))  # filtre 0 par ligne

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b""))


@tool("screenshot", "Capture tous les écrans dans un PNG du dossier Images/Jarvis et renvoie son chemin.",
      Level.N2, private=True)
def screenshot() -> dict:
    png = _png(*_capture())
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / f"capture-{datetime.now():%Y%m%d-%H%M%S}.png"
    with open(path, "xb") as f:  # jamais d'écrasement
        f.write(png)
    return {"path": str(path), "bytes": len(png)}
