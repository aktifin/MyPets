from __future__ import annotations

from fastapi.testclient import TestClient

from mypets_backend.release import APP_VERSION, RELEASE_CHANNEL


def test_health_exposes_release_metadata(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": APP_VERSION,
        "channel": RELEASE_CHANNEL,
    }


def test_openapi_uses_the_same_release_version(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == APP_VERSION
