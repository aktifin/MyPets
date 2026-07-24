from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mypets_backend.config import Settings
from mypets_backend.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'backend.sqlite3'}",
        jwt_secret="test-secret-with-more-than-24-characters",
        environment="test",
        access_token_minutes=30,
        device_token_hours=12,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


@pytest.fixture
def account_auth(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "owner_1",
            "display_name": "主人",
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def bind_device(
    client: TestClient,
    account_auth: dict[str, str],
    *,
    public_id: str = "windows-device-0001",
    name: str = "工作电脑",
) -> tuple[dict, dict[str, str], str]:
    bound = client.post(
        "/api/v1/devices/bind",
        headers=account_auth,
        json={"public_id": public_id, "name": name, "platform": "windows"},
    )
    assert bound.status_code == 201, bound.text
    binding = bound.json()
    exchanged = client.post(
        "/api/v1/auth/device-token",
        json={
            "device_id": binding["device"]["id"],
            "device_secret": binding["device_secret"],
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    headers = {"Authorization": f"Bearer {exchanged.json()['access_token']}"}
    return binding["device"], headers, binding["device_secret"]
