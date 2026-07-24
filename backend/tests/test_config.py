import pytest

from mypets_backend.config import Settings


def test_production_rejects_default_secret() -> None:
    with pytest.raises(ValueError, match="生产环境"):
        Settings(environment="production").validate()


def test_short_secret_is_rejected() -> None:
    with pytest.raises(ValueError, match="24"):
        Settings(jwt_secret="too-short").validate()
