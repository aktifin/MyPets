from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mypets_backend.config import Settings
from mypets_backend.main import create_app

from .conftest import register_account
from .test_admin_publishing import _package_bytes


@pytest.fixture
def role_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'roles.sqlite3'}",
        jwt_secret="role-test-secret-with-more-than-24-characters",
        environment="test",
        access_token_minutes=30,
        device_token_hours=12,
        admin_editor_usernames=("pet_editor",),
        admin_reviewer_usernames=("pet_reviewer",),
        admin_publisher_usernames=("pet_publisher",),
        admin_auditor_usernames=("pet_auditor",),
        admin_superadmin_usernames=("pet_root",),
        asset_storage_dir=str(tmp_path / "assets"),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


def _create_template(client: TestClient, auth: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/admin/pet-templates",
        headers=auth,
        json={
            "template_code": "official.cat.governed",
            "display_name": "分权白猫",
            "species": "cat",
            "description": "用于权限和回滚测试",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_version(
    client: TestClient,
    auth: dict[str, str],
    template_id: str,
    *,
    template_version: str,
    asset_version: str,
) -> dict:
    response = client.post(
        f"/api/v1/admin/pet-templates/{template_id}/versions",
        headers=auth,
        json={
            "template_version": template_version,
            "identity_version": "1.0.0",
            "asset_version": asset_version,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload_submit_approve_publish(
    client: TestClient,
    *,
    editor: dict[str, str],
    reviewer: dict[str, str],
    publisher: dict[str, str],
    version_id: str,
    asset_version: str,
) -> dict:
    uploaded = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/package",
        headers=editor,
        files={
            "package": (
                "pet.zip",
                _package_bytes(
                    template_id="official.cat.governed",
                    asset_version=asset_version,
                ),
                "application/zip",
            )
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    submitted = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/submit-review",
        headers=editor,
    )
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/approve",
        headers=reviewer,
        json={"comment": "视觉与技术检查通过"},
    )
    assert approved.status_code == 200, approved.text
    published = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/publish",
        headers=publisher,
    )
    assert published.status_code == 201, published.text
    return published.json()


def _package_with_native_wave(*, asset_version: str) -> bytes:
    idle_buffer = io.BytesIO()
    wave_buffer = io.BytesIO()
    Image.new("RGBA", (32, 32), (255, 255, 255, 255)).save(idle_buffer, format="PNG")
    Image.new("RGBA", (32, 32), (30, 100, 220, 255)).save(wave_buffer, format="PNG")
    idle = idle_buffer.getvalue()
    wave = wave_buffer.getvalue()
    manifest = {
        "schema_version": "2.1",
        "template_id": "official.cat.governed",
        "identity_version": "1.0.0",
        "asset_version": asset_version,
        "animations": {"idle": ["idle.png"], "wave": ["wave.png", "idle.png"]},
        "fallback_actions": {
            name: "idle"
            for name in (
                "walk",
                "sit",
                "sleep",
                "happy",
                "shy",
                "surprised",
                "annoyed",
                "sleepy",
                "curious",
                "selfie",
                "drag",
            )
        },
        "files": [
            {
                "path": "idle.png",
                "size": len(idle),
                "sha256": hashlib.sha256(idle).hexdigest(),
            },
            {
                "path": "wave.png",
                "size": len(wave),
                "sha256": hashlib.sha256(wave).hexdigest(),
            },
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("idle.png", idle)
        archive.writestr("wave.png", wave)
    return output.getvalue()


def test_role_permissions_separate_edit_review_publish_and_audit(
    role_client: TestClient,
) -> None:
    editor = register_account(role_client, "pet_editor")
    reviewer = register_account(role_client, "pet_reviewer")
    publisher = register_account(role_client, "pet_publisher")
    auditor = register_account(role_client, "pet_auditor")
    root = register_account(role_client, "pet_root")

    identity = role_client.get("/api/v1/admin/me", headers=editor)
    assert identity.status_code == 200
    assert identity.json()["roles"] == ["editor"]
    assert identity.json()["permissions"] == ["edit", "view"]

    denied_create = role_client.post(
        "/api/v1/admin/pet-templates",
        headers=reviewer,
        json={"template_code": "official.denied.role", "display_name": "拒绝", "species": "cat"},
    )
    assert denied_create.status_code == 403
    assert denied_create.json()["required_permission"] == "edit"

    template = _create_template(role_client, editor)
    version = _create_version(
        role_client,
        editor,
        template["id"],
        template_version="1.0.0",
        asset_version="1.0.0",
    )
    assert role_client.post(
        f"/api/v1/admin/pet-template-versions/{version['id']}/package",
        headers=editor,
        files={
            "package": (
                "pet.zip",
                _package_bytes(
                    template_id="official.cat.governed",
                    asset_version="1.0.0",
                ),
                "application/zip",
            )
        },
    ).status_code == 200
    assert role_client.post(
        f"/api/v1/admin/pet-template-versions/{version['id']}/submit-review",
        headers=editor,
    ).status_code == 200

    editor_approve = role_client.post(
        f"/api/v1/admin/pet-template-versions/{version['id']}/approve",
        headers=editor,
        json={"comment": "越权"},
    )
    assert editor_approve.status_code == 403
    reviewer_approve = role_client.post(
        f"/api/v1/admin/pet-template-versions/{version['id']}/approve",
        headers=reviewer,
        json={"comment": "通过"},
    )
    assert reviewer_approve.status_code == 200

    reviewer_publish = role_client.post(
        f"/api/v1/admin/pet-template-versions/{version['id']}/publish",
        headers=reviewer,
    )
    assert reviewer_publish.status_code == 403
    assert role_client.post(
        f"/api/v1/admin/pet-template-versions/{version['id']}/publish",
        headers=publisher,
    ).status_code == 201

    assert role_client.get("/api/v1/admin/audit-logs", headers=editor).status_code == 403
    assert role_client.get("/api/v1/admin/audit-logs", headers=auditor).status_code == 200
    root_identity = role_client.get("/api/v1/admin/me", headers=root).json()
    assert root_identity["roles"] == ["superadmin"]
    assert set(root_identity["permissions"]) == {
        "audit",
        "edit",
        "manage",
        "publish",
        "review",
        "view",
    }


def test_publish_activates_stable_channel_and_publisher_can_rollback(
    role_client: TestClient,
) -> None:
    editor = register_account(role_client, "pet_editor")
    reviewer = register_account(role_client, "pet_reviewer")
    publisher = register_account(role_client, "pet_publisher")
    template = _create_template(role_client, editor)

    first_version = _create_version(
        role_client,
        editor,
        template["id"],
        template_version="1.0.0",
        asset_version="1.0.0",
    )
    first_release = _upload_submit_approve_publish(
        role_client,
        editor=editor,
        reviewer=reviewer,
        publisher=publisher,
        version_id=first_version["id"],
        asset_version="1.0.0",
    )

    second_version = _create_version(
        role_client,
        editor,
        template["id"],
        template_version="1.1.0",
        asset_version="2.0.0",
    )
    second_release = _upload_submit_approve_publish(
        role_client,
        editor=editor,
        reviewer=reviewer,
        publisher=publisher,
        version_id=second_version["id"],
        asset_version="2.0.0",
    )

    deployment = role_client.get(
        "/api/v1/admin/pet-asset-deployments",
        headers=publisher,
    )
    assert deployment.status_code == 200
    assert deployment.json()[0]["active_release"]["release_id"] == second_release["release_id"]
    latest = role_client.get(
        "/api/v1/catalog/pet-assets/latest",
        params={"template_id": "official.cat.governed"},
    )
    assert latest.status_code == 200
    assert latest.json()["release_id"] == second_release["release_id"]

    rolled_back = role_client.post(
        "/api/v1/admin/pet-asset-deployments/official.cat.governed/rollback",
        headers=publisher,
        json={
            "release_id": first_release["release_id"],
            "reason": "新版本在高 DPI 预览中出现裁切，恢复上一稳定版",
        },
    )
    assert rolled_back.status_code == 200, rolled_back.text
    payload = rolled_back.json()
    assert payload["active_release"]["release_id"] == first_release["release_id"]
    assert payload["previous_release"]["release_id"] == second_release["release_id"]
    latest_after = role_client.get(
        "/api/v1/catalog/pet-assets/latest",
        params={"template_id": "official.cat.governed"},
    )
    assert latest_after.json()["release_id"] == first_release["release_id"]


def test_visual_comparison_reports_action_and_version_changes(role_client: TestClient) -> None:
    editor = register_account(role_client, "pet_editor")
    template = _create_template(role_client, editor)
    left = _create_version(
        role_client,
        editor,
        template["id"],
        template_version="1.0.0",
        asset_version="1.0.0",
    )
    right = _create_version(
        role_client,
        editor,
        template["id"],
        template_version="1.1.0",
        asset_version="2.0.0",
    )
    assert role_client.post(
        f"/api/v1/admin/pet-template-versions/{left['id']}/package",
        headers=editor,
        files={
            "package": (
                "left.zip",
                _package_bytes(
                    template_id="official.cat.governed",
                    asset_version="1.0.0",
                ),
                "application/zip",
            )
        },
    ).status_code == 200
    assert role_client.post(
        f"/api/v1/admin/pet-template-versions/{right['id']}/package",
        headers=editor,
        files={
            "package": (
                "right.zip",
                _package_with_native_wave(asset_version="2.0.0"),
                "application/zip",
            )
        },
    ).status_code == 200

    comparison = role_client.get(
        "/api/v1/admin/pet-template-versions/compare",
        headers=editor,
        params={"left_id": left["id"], "right_id": right["id"]},
    )
    assert comparison.status_code == 200, comparison.text
    payload = comparison.json()
    assert payload["asset_version_changed"] is True
    assert payload["package_hash_changed"] is True
    wave = next(item for item in payload["action_changes"] if item["name"] == "wave")
    assert wave["change"] == "changed"
    assert wave["left"]["fallback_to"] == "idle"
    assert wave["right"]["frame_count"] == 2
