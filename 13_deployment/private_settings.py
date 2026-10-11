"""Current-user Windows DPAPI storage. Never print or log decrypted values."""
from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

MAGIC = b"PSYNOVA-DPAPI-v1\x00"


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def transform(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise OSError("Windows current-user protection required")
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    action = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    action.restype = wintypes.BOOL
    # UI_FORBIDDEN; default scope is current user, not LOCAL_MACHINE.
    if not action(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Private settings protection unavailable")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def write_private(path: Path, values: dict) -> None:
    payload = json.dumps(values).encode("utf-8")
    path.write_bytes(MAGIC + transform(payload))


def read_private(path: Path) -> dict:
    payload = path.read_bytes()
    if not payload.startswith(MAGIC):
        raise ValueError("Unsupported private settings container")
    result = json.loads(transform(payload[len(MAGIC):], decrypt=True))
    if not isinstance(result, dict):
        raise TypeError("Invalid private settings container")
    return result
