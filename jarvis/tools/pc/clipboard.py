"""Presse-papiers texte : clipboard_write (N1) et clipboard_read (N2, privé, contenu tiers). ctypes."""
import ctypes
import time
from contextlib import contextmanager
from ctypes import wintypes

from jarvis.core.tools import Level, tool

CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
READ_MAX = 4000  # le LLM n'en voit de toute façon que 2 000 (as_data)
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32.OpenClipboard.argtypes = [wintypes.HWND]
_u32.GetClipboardData.restype = wintypes.HANDLE
_u32.GetClipboardData.argtypes = [wintypes.UINT]
_u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_k32.GlobalAlloc.restype = wintypes.HANDLE
_k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_k32.GlobalLock.restype = ctypes.c_void_p
_k32.GlobalLock.argtypes = [wintypes.HANDLE]
_k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
_k32.GlobalFree.argtypes = [wintypes.HANDLE]


@contextmanager
def _clipboard():
    for _ in range(10):  # une autre application peut le tenir un instant
        if _u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("presse-papiers occupé")
    try:
        yield
    finally:
        _u32.CloseClipboard()


def _set_text(text: str) -> None:
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    handle = _k32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        raise OSError("mémoire insuffisante")
    ctypes.memmove(_k32.GlobalLock(handle), data, size)
    _k32.GlobalUnlock(handle)
    with _clipboard():
        _u32.EmptyClipboard()
        if not _u32.SetClipboardData(CF_UNICODETEXT, handle):
            _k32.GlobalFree(handle)  # sinon le système en est propriétaire
            raise OSError("écriture dans le presse-papiers impossible")


def _get_text() -> str:
    with _clipboard():
        handle = _u32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""  # vide, ou contenu non textuel
        pointer = _k32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _k32.GlobalUnlock(handle)


@tool("clipboard_write", "Copie un texte dans le presse-papiers (remplace son contenu).", Level.N1, text=str)
def clipboard_write(text: str) -> dict:
    _set_text(text)
    return {"chars": len(text)}


@tool("clipboard_read", "Lit le texte du presse-papiers (peut contenir des mots de passe).", Level.N2,
      private=True, external=True)
def clipboard_read() -> dict:
    text = _get_text()
    return {"text": text[:READ_MAX], "chars": len(text), "truncated": len(text) > READ_MAX}
