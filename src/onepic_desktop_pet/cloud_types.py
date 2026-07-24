"""Pure value objects and validation helpers for the MyPets cloud connection."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit


def normalize_base_url(value: str) -> str:
    """Return a canonical HTTP(S) API origin without credentials, query, or fragment."""

    raw = value.strip()
    if not raw:
        raise ValueError("云端服务地址不能为空")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("云端服务地址必须使用 http 或 https")
    if not parsed.hostname:
        raise ValueError("云端服务地址缺少主机名")
    if parsed.username or parsed.password:
        raise ValueError("云端服务地址不能包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("云端服务地址不能包含查询参数或片段")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, path, "", ""))


def credential_target(base_url: str) -> str:
    """Create a stable, non-secret Credential Manager target for one backend origin."""

    normalized = normalize_base_url(base_url)
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"MyPets/device/{digest}"


@dataclass(frozen=True)
class DeviceCredentials:
    """Long-lived device binding material; access tokens are deliberately excluded."""

    base_url: str
    account_id: str
    device_id: str
    device_secret: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", normalize_base_url(self.base_url))
        for field_name in ("account_id", "device_id", "device_secret"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} 不能为空")
            object.__setattr__(self, field_name, value)
        if len(self.device_secret) < 32:
            raise ValueError("device_secret 长度不足")


@dataclass(frozen=True)
class CloudIdentity:
    """In-memory authenticated account/device identity."""

    account_id: str
    device_id: str
    display_name: str

    def __post_init__(self) -> None:
        if not self.account_id.strip() or not self.device_id.strip():
            raise ValueError("账户和设备标识不能为空")
