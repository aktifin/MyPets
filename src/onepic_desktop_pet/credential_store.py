"""Secure storage for MyPets device credentials.

On Windows this module uses Credential Manager through Win32 APIs. It never persists account or
short-lived device access tokens. Tests can inject ``MemoryCredentialStore``.
"""

from __future__ import annotations

import ctypes
import json
import sys
from abc import ABC, abstractmethod
from ctypes import wintypes
from typing import Any

from .cloud_types import DeviceCredentials, credential_target


class CredentialStore(ABC):
    @abstractmethod
    def load(self, base_url: str) -> DeviceCredentials | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, credentials: DeviceCredentials) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, base_url: str) -> None:
        raise NotImplementedError


class MemoryCredentialStore(CredentialStore):
    """Non-persistent store for tests and explicit dependency injection."""

    def __init__(self) -> None:
        self._items: dict[str, DeviceCredentials] = {}

    def load(self, base_url: str) -> DeviceCredentials | None:
        return self._items.get(credential_target(base_url))

    def save(self, credentials: DeviceCredentials) -> None:
        self._items[credential_target(credentials.base_url)] = credentials

    def delete(self, base_url: str) -> None:
        self._items.pop(credential_target(base_url), None)


class UnsupportedCredentialStore(CredentialStore):
    """Fail closed on unsupported platforms instead of writing secrets to a plaintext file."""

    def load(self, base_url: str) -> DeviceCredentials | None:
        return None

    def save(self, credentials: DeviceCredentials) -> None:
        raise RuntimeError("当前平台未提供安全凭据存储")

    def delete(self, base_url: str) -> None:
        return None


if sys.platform == "win32":
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    class CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
        _fields_ = [
            ("Keyword", wintypes.LPWSTR),
            ("Flags", wintypes.DWORD),
            ("ValueSize", wintypes.DWORD),
            ("Value", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTEW)),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    PCREDENTIALW = ctypes.POINTER(CREDENTIALW)


class WindowsCredentialStore(CredentialStore):
    """Windows Credential Manager adapter using generic credentials."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsCredentialStore 只能在 Windows 使用")
        self._advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(PCREDENTIALW),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi32.CredFree.restype = None

    @staticmethod
    def _serialize(credentials: DeviceCredentials) -> bytes:
        payload: dict[str, Any] = {
            "version": 1,
            "base_url": credentials.base_url,
            "account_id": credentials.account_id,
            "device_id": credentials.device_id,
            "device_secret": credentials.device_secret,
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 2500:
            raise ValueError("设备凭据超过 Credential Manager 大小限制")
        return encoded

    def save(self, credentials: DeviceCredentials) -> None:
        encoded = self._serialize(credentials)
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        target = credential_target(credentials.base_url)
        record = CREDENTIALW()
        record.Type = CRED_TYPE_GENERIC
        record.TargetName = target
        record.Comment = "MyPets cloud device credential"
        record.CredentialBlobSize = len(encoded)
        record.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        record.Persist = CRED_PERSIST_LOCAL_MACHINE
        record.UserName = credentials.account_id
        if not self._advapi32.CredWriteW(ctypes.byref(record), 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def load(self, base_url: str) -> DeviceCredentials | None:
        target = credential_target(base_url)
        pointer = PCREDENTIALW()
        if not self._advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == ERROR_NOT_FOUND:
                return None
            raise ctypes.WinError(error)
        try:
            record = pointer.contents
            raw = ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize)
            data = json.loads(raw.decode("utf-8"))
            if data.get("version") != 1:
                raise ValueError("不支持的设备凭据版本")
            return DeviceCredentials(
                base_url=data["base_url"],
                account_id=data["account_id"],
                device_id=data["device_id"],
                device_secret=data["device_secret"],
            )
        finally:
            self._advapi32.CredFree(pointer)

    def delete(self, base_url: str) -> None:
        target = credential_target(base_url)
        if self._advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != ERROR_NOT_FOUND:
            raise ctypes.WinError(error)


def default_credential_store() -> CredentialStore:
    return WindowsCredentialStore() if sys.platform == "win32" else UnsupportedCredentialStore()
