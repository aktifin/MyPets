"""Environment-backed backend configuration without importing desktop settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

_DEVELOPMENT_SECRET = "development-only-change-me"


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the modular-monolith API."""

    database_url: str = "sqlite:///./mypets-backend.sqlite3"
    jwt_secret: str = _DEVELOPMENT_SECRET
    environment: str = "development"
    access_token_minutes: int = 30
    device_token_hours: int = 12
    create_schema_on_start: bool = True

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
        )
        settings.validate()
        return settings

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
