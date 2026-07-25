from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mypets_backend.config import Settings
from mypets_backend.main import create_app


@pytest.fixture
def review_disabled_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'review-disabled.sqlite3'}",
        jwt_secret="review-disabled-test-secret-more-than-24-chars",
        environment="test",
        access_token_minutes=30,
        device_token_hours=12,
        pet_review_enabled=False,
        admin_usernames=("disabled_admin",),
        asset_storage_dir=str(tmp_path / "assets"),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


def _register(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "review_disabled_owner",
            "display_name": "普通用户",
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_review_routes_and_web_entry_points_are_absent(
    review_disabled_client: TestClient,
) -> None:
    client = review_disabled_client
    auth = _register(client)

    portal = client.get("/portal")
    assert portal.status_code == 200, portal.text
    assert "/portal/asset-submissions.js" not in portal.text
    assert "/portal/asset-production.js" not in portal.text
    assert "专属形象" not in portal.text

    assert client.get("/portal/asset-submissions.js").status_code == 404
    assert client.get("/portal/asset-production.js").status_code == 404
    assert client.get("/admin").status_code == 404

    hidden_paths = (
        ("GET", "/api/v1/pet-asset-submissions"),
        ("GET", "/api/v1/pet-asset-production-jobs"),
        ("GET", "/api/v1/pets/unknown/personal-asset-deployment"),
        ("GET", "/api/v1/admin/pet-templates"),
        ("GET", "/api/v1/admin/pet-asset-submissions"),
        ("GET", "/api/v1/admin/pet-asset-production-jobs"),
        ("GET", "/api/v1/admin/pet-asset-deployment-reviews"),
    )
    for method, path in hidden_paths:
        response = client.request(method, path, headers=auth)
        assert response.status_code == 404, (path, response.text)
        assert response.json()["detail"] == "Not Found"


def test_read_only_published_asset_catalog_remains_registered(
    review_disabled_client: TestClient,
) -> None:
    client = review_disabled_client
    exact = client.get(
        "/api/v1/catalog/pet-assets",
        params={
            "template_id": "official.cat.white",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert exact.status_code == 404
    assert exact.json()["detail"] == "未找到匹配的已发布宠物形象包"

    latest = client.get(
        "/api/v1/catalog/pet-assets/latest",
        params={"template_id": "official.cat.white"},
    )
    assert latest.status_code == 404
    assert latest.json()["detail"] == "该宠物模板没有稳定发布版本"


def test_environment_flag_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYPETS_ENABLE_PET_REVIEW", raising=False)
    assert Settings.from_env().pet_review_enabled is False

    monkeypatch.setenv("MYPETS_ENABLE_PET_REVIEW", "true")
    assert Settings.from_env().pet_review_enabled is True
