import pytest

from mypets_backend.config import Settings


_PRODUCTION_SECRET = "production-secret-with-at-least-24-chars"


def test_production_rejects_default_secret() -> None:
    with pytest.raises(ValueError, match="生产环境"):
        Settings(environment="production").validate()


def test_production_rejects_startup_schema_creation() -> None:
    with pytest.raises(ValueError, match="Alembic upgrade head"):
        Settings(
            environment="production",
            jwt_secret=_PRODUCTION_SECRET,
            create_schema_on_start=True,
        ).validate()


def test_production_environment_defaults_schema_creation_off(monkeypatch) -> None:
    monkeypatch.setenv("MYPETS_ENVIRONMENT", "production")
    monkeypatch.setenv("MYPETS_JWT_SECRET", _PRODUCTION_SECRET)
    monkeypatch.delenv("MYPETS_CREATE_SCHEMA_ON_START", raising=False)

    settings = Settings.from_env()

    assert settings.environment == "production"
    assert settings.create_schema_on_start is False


def test_development_environment_keeps_startup_schema_creation(monkeypatch) -> None:
    monkeypatch.setenv("MYPETS_ENVIRONMENT", "development")
    monkeypatch.delenv("MYPETS_CREATE_SCHEMA_ON_START", raising=False)

    settings = Settings.from_env()

    assert settings.create_schema_on_start is True


def test_short_secret_is_rejected() -> None:
    with pytest.raises(ValueError, match="24"):
        Settings(jwt_secret="too-short").validate()
