from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wt.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob_from_bytes(data: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(data, len(data))
    ptr = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    return DATA_BLOB(len(data), ptr)


def _bytes_from_blob(blob: DATA_BLOB) -> bytes:
    if not blob.cbData:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def protect(plaintext: str) -> str:
    """Encrypt text with the current Windows user's DPAPI key; base64-like hex output."""
    import base64

    raw = plaintext.encode("utf-8")
    in_blob = _blob_from_bytes(raw)
    out_blob = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        encrypted = _bytes_from_blob(out_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    return base64.b64encode(encrypted).decode("ascii")


def unprotect(ciphertext: str) -> str:
    """Decrypt text produced by :func:`protect` for the current Windows user."""
    import base64

    try:
        raw = base64.b64decode(ciphertext.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError("无效的加密数据") from exc
    in_blob = _blob_from_bytes(raw)
    out_blob = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return _bytes_from_blob(out_blob).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)
