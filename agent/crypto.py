"""
Cryptographic Protection and DPAPI Bindings for SentinelX Endpoint Agent.

Uses Windows Data Protection API (DPAPI) via ctypes to encrypt device secrets
at rest with machine/system-level isolation.
"""

from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import wintypes
from typing import Optional

# Windows DPAPI Constants
CRYPTPROTECT_UI_FORBIDDEN = 0x1
CRYPTPROTECT_LOCAL_MACHINE = 0x4


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _get_dpapi_functions():
    """Initializes Windows crypt32.dll functions if on Windows."""
    if sys.platform != "win32":
        return None, None

    try:
        crypt32 = ctypes.windll.crypt32

        # CryptProtectData
        CryptProtectData = crypt32.CryptProtectData
        CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),          # pDataIn
            wintypes.LPCWSTR,                   # szDataDescr
            ctypes.POINTER(DATA_BLOB),          # pOptionalEntropy
            ctypes.c_void_p,                    # pvReserved
            ctypes.c_void_p,                    # pPromptStruct
            wintypes.DWORD,                     # dwFlags
            ctypes.POINTER(DATA_BLOB),          # pDataOut
        ]
        CryptProtectData.restype = wintypes.BOOL

        # CryptUnprotectData
        CryptUnprotectData = crypt32.CryptUnprotectData
        CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),          # pDataIn
            ctypes.POINTER(wintypes.LPWSTR),    # ppszDataDescr
            ctypes.POINTER(DATA_BLOB),          # pOptionalEntropy
            ctypes.c_void_p,                    # pvReserved
            ctypes.c_void_p,                    # pPromptStruct
            wintypes.DWORD,                     # dwFlags
            ctypes.POINTER(DATA_BLOB),          # pDataOut
        ]
        CryptUnprotectData.restype = wintypes.BOOL

        return CryptProtectData, CryptUnprotectData
    except Exception:
        return None, None


_CryptProtectData, _CryptUnprotectData = _get_dpapi_functions()


def dpapi_encrypt(plaintext: str | bytes, entropy: Optional[str] = "SentinelX_Agent_v1") -> str:
    """
    Encrypts sensitive data using Windows DPAPI.
    Returns a base64-encoded ciphertext string.
    """
    if isinstance(plaintext, str):
        data_bytes = plaintext.encode("utf-8")
    else:
        data_bytes = plaintext

    if _CryptProtectData is None:
        # Fallback for non-Windows dev / testing: base64 obfuscation with warning
        return "b64:" + base64.b64encode(data_bytes).decode("ascii")

    in_blob = DATA_BLOB()
    in_blob.cbData = len(data_bytes)
    in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(data_bytes), ctypes.POINTER(ctypes.c_byte))

    entropy_blob = None
    if entropy:
        ent_bytes = entropy.encode("utf-8")
        entropy_blob = DATA_BLOB()
        entropy_blob.cbData = len(ent_bytes)
        entropy_blob.pbData = ctypes.cast(ctypes.create_string_buffer(ent_bytes), ctypes.POINTER(ctypes.c_byte))

    out_blob = DATA_BLOB()
    descr = "SentinelX Agent Device Key"

    # Try machine-level DPAPI first (readable by SYSTEM and Administrators)
    flags = CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE
    success = _CryptProtectData(
        ctypes.byref(in_blob),
        descr,
        ctypes.byref(entropy_blob) if entropy_blob else None,
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )

    if not success:
        # Fallback to current-user DPAPI
        flags = CRYPTPROTECT_UI_FORBIDDEN
        success = _CryptProtectData(
            ctypes.byref(in_blob),
            descr,
            ctypes.byref(entropy_blob) if entropy_blob else None,
            None,
            None,
            flags,
            ctypes.byref(out_blob),
        )

    if not success:
        raise OSError(f"DPAPI CryptProtectData failed with Windows error: {ctypes.GetLastError()}")

    try:
        encrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return "dpapi:" + base64.b64encode(encrypted_bytes).decode("ascii")
    finally:
        # LocalFree memory allocated by DPAPI
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def dpapi_decrypt(ciphertext: str, entropy: Optional[str] = "SentinelX_Agent_v1") -> str:
    """
    Decrypts base64-encoded DPAPI ciphertext.
    Returns the original plaintext string.
    """
    if ciphertext.startswith("b64:"):
        return base64.b64decode(ciphertext[4:]).decode("utf-8")

    if not ciphertext.startswith("dpapi:"):
        # Legacy or plain string fallback
        return ciphertext

    if _CryptUnprotectData is None:
        raise RuntimeError("DPAPI is only available on Windows systems.")

    encrypted_bytes = base64.b64decode(ciphertext[6:])

    in_blob = DATA_BLOB()
    in_blob.cbData = len(encrypted_bytes)
    in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_byte))

    entropy_blob = None
    if entropy:
        ent_bytes = entropy.encode("utf-8")
        entropy_blob = DATA_BLOB()
        entropy_blob.cbData = len(ent_bytes)
        entropy_blob.pbData = ctypes.cast(ctypes.create_string_buffer(ent_bytes), ctypes.POINTER(ctypes.c_byte))

    out_blob = DATA_BLOB()
    flags = CRYPTPROTECT_UI_FORBIDDEN

    success = _CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob) if entropy_blob else None,
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )

    if not success:
        raise OSError(f"DPAPI CryptUnprotectData failed with Windows error: {ctypes.GetLastError()}")

    try:
        decrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return decrypted_bytes.decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def mask_secret(secret: str | None) -> str:
    """Masks secret tokens and keys for safe logging (e.g. sxe_1234...ef56)."""
    if not secret:
        return "<none>"
    s = str(secret).strip()
    if len(s) <= 8:
        return "********"
    return f"{s[:6]}...{s[-4:]}"

