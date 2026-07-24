"""Environment-backed backend configuration without importing desktop settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_DEVELOPMENT_SECRET = "development-only-change-me"


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(sorted({item.strip().lower() for item in value.split(",") if item.strip()}))


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the modular-monolith API."""

    database_url: str = "sqlite:///./mypets-backend.sqlite3"
    jwt_secret: str = _DEVELOPMENT_SECRET
    environment: str = "development"
    access_token_minutes: int = 30
    device_token_hours: int = 12
    create_schema_on_start: bool = True

    # MYPETS_ADMIN_USERNAMES remains a backward-compatible super-administrator list.
    # Explicit role lists are merged into admin_usernames in __post_init__ so the
    # existing administrator dependencies continue to recognize every role.
    admin_usernames: tuple[str, ...] = ()
    admin_superadmin_usernames: tuple[str, ...] = ()
    admin_editor_usernames: tuple[str, ...] = ()
    admin_reviewer_usernames: tuple[str, ...] = ()
    admin_publisher_usernames: tuple[str, ...] = ()
    admin_auditor_usernames: tuple[str, ...] = ()
    admin_legacy_usernames: tuple[str, ...] = field(default=(), init=False, repr=False)

    asset_storage_dir: str = "./mypets-assets"
    max_asset_package_bytes: int = 32 * 1024 * 1024
    max_asset_uncompressed_bytes: int = 128 * 1024 * 1024
    max_asset_files: int = 512

    def __post_init__(self) -> None:
        legacy = _csv_values(",".join(self.admin_usernames))
        object.__setattr__(self, "admin_legacy_usernames", legacy)
        role_values = (
            legacy,
            self.admin_superadmin_usernames,
            self.admin_editor_usernames,
            self.admin_reviewer_usernames,
            self.admin_publisher_usernames,
            self.admin_auditor_usernames,
        )
        merged = tuple(sorted({name.lower() for values in role_values for name in values}))
        object.__setattr__(self, "admin_usernames", merged)

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            database_url=os.getenv("MYPETS_DATABASE_URL", cls.database_url),
            jwt_secret=os.getenv("MYPETS_JWT_SECRET", cls.jwt_secret),
            environment=os.getenv("MYPETS_ENVIRONMENT", cls.environment).lower(),
            access_token_minutes=int(
                os.getenv("MYPETS_ACCESS_TOKEN_MINUTES", cls.access_token_minutes)
            ),
            device_token_hours=int(
                os.getenv("MYPETS_DEVICE_TOKEN_HOURS", cls.device_token_hours)
            ),
            create_schema_on_start=os.getenv(
                "MYPETS_CREATE_SCHEMA_ON_START", "1"
            ).lower()
            not in {"0", "false", "no"},
            admin_usernames=_csv_values(os.getenv("MYPETS_ADMIN_USERNAMES", "")),
            admin_superadmin_usernames=_csv_values(
                os.getenv("MYPETS_ADMIN_SUPERADMINS", "")
            ),
            admin_editor_usernames=_csv_values(os.getenv("MYPETS_ADMIN_EDITORS", "")),
            admin_reviewer_usernames=_csv_values(
                os.getenv("MYPETS_ADMIN_REVIEWERS", "")
            ),
            admin_publisher_usernames=_csv_values(
                os.getenv("MYPETS_ADMIN_PUBLISHERS", "")
            ),
            admin_auditor_usernames=_csv_values(
                os.getenv("MYPETS_ADMIN_AUDITORS", "")
            ),
            asset_storage_dir=os.getenv("MYPETS_ASSET_STORAGE_DIR", cls.asset_storage_dir),
            max_asset_package_bytes=int(
                os.getenv("MYPETS_MAX_ASSET_PACKAGE_BYTES", cls.max_asset_package_bytes)
            ),
            max_asset_uncompressed_bytes=int(
                os.getenv(
                    "MYPETS_MAX_ASSET_UNCOMPRESSED_BYTES",
                    cls.max_asset_uncompressed_bytes,
                )
            ),
            max_asset_files=int(os.getenv("MYPETS_MAX_ASSET_FILES", cls.max_asset_files)),
        )
        settings.validate()
        return settings

    @property
    def asset_storage_path(self) -> Path:
        return Path(self.asset_storage_dir).expanduser().resolve()

    def roles_for_username(self, username: str) -> tuple[str, ...]:
        normalized = username.strip().lower()
        roles: set[str] = set()
        if normalized in self.admin_legacy_usernames or normalized in self.admin_superadmin_usernames:
            roles.add("superadmin")
        if normalized in self.admin_editor_usernames:
            roles.add("editor")
        if normalized in self.admin_reviewer_usernames:
            roles.add("reviewer")
        if normalized in self.admin_publisher_usernames:
            roles.add("publisher")
        if normalized in self.admin_auditor_usernames:
            roles.add("auditor")
        return tuple(sorted(roles))

    def validate(self) -> None:
        if not self.database_url.strip():
            raise ValueError("MYPETS_DATABASE_URL 不能为空")
        if len(self.jwt_secret) < 24:
            raise ValueError("MYPETS_JWT_SECRET 至少需要 24 个字符")
        if self.environment == "production" and self.jwt_secret == _DEVELOPMENT_SECRET:
            raise ValueError("生产环境禁止使用开发默认 JWT 密钥")
        if self.access_token_minutes < 5:
            raise ValueError("账户访问令牌有效期不能短于 5 分钟")
        if self.device_token_hours < 1:
            raise ValueError("设备访问令牌有效期不能短于 1 小时")
        if not self.asset_storage_dir.strip():
            raise ValueError("MYPETS_ASSET_STORAGE_DIR 不能为空")
        if self.max_asset_package_bytes < 1024:
            raise ValueError("素材包压缩大小上限不能小于 1 KiB")
        if self.max_asset_uncompressed_bytes < self.max_asset_package_bytes:
            raise ValueError("素材包解压大小上限不能小于压缩大小上限")
        if not 1 <= self.max_asset_files <= 10000:
            raise ValueError("素材包文件数量上限必须位于 1 到 10000")
