from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging

CRYPTPROTECT_UI_FORBIDDEN = 0x01

LOGGER = logging.getLogger(__name__)

# use_last_error=True：调用前后由 ctypes 保存线程 last error，
# 配合 ctypes.get_last_error() 取值，避免中间 Python 字节码改写错误码
    # 导致 DPAPI 失败诊断信息失真
_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
# 显式声明参数与返回类型，避免 64 位下指针被截断
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


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


def _local_free(blob: DATA_BLOB) -> None:
    """释放 DPAPI 返回的本地内存；失败仅告警，不中断清理路径。"""
    if _kernel32.LocalFree(blob.pbData):
        LOGGER.warning("LocalFree 释放内存失败")


def protect(plaintext: str) -> str:
    """Encrypt text with the current Windows user's DPAPI key; base64-like hex output."""
    import base64

    raw = plaintext.encode("utf-8")
    in_blob = _blob_from_bytes(raw)
    out_blob = DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        # 带上系统错误信息，便于定位失败原因
        raise OSError(
            f"CryptProtectData 失败: {ctypes.WinError(ctypes.get_last_error())}"
        )
    try:
        encrypted = _bytes_from_blob(out_blob)
    finally:
        _local_free(out_blob)
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
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        # 带上系统错误信息，便于定位失败原因
        raise OSError(
            f"CryptUnprotectData 失败: {ctypes.WinError(ctypes.get_last_error())}"
        )
    try:
        return _bytes_from_blob(out_blob).decode("utf-8")
    finally:
        _local_free(out_blob)
