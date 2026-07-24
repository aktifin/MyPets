from __future__ import annotations

import hashlib
import io
import json
import zipfile

from PIL import Image

from fastapi.testclient import TestClient
from sqlalchemy import select

from mypets_backend.models import AdminAuditLog, PetAssetRelease, PetTemplateVersion

from .conftest import register_account


def _package_bytes(
    *,
    template_id: str = "official.cat.white",
    identity_version: str = "1.0.0",
    asset_version: str = "2.0.0",
    unsafe_name: str | None = None,
) -> bytes:
    image_buffer = io.BytesIO()
    Image.new("RGBA", (32, 32), (255, 255, 255, 255)).save(image_buffer, format="PNG")
    frame = image_buffer.getvalue()
    manifest = {
        "schema_version": "2.1",
        "template_id": template_id,
        "identity_version": identity_version,
        "asset_version": asset_version,
        "animations": {"idle": ["frame.png"]},
        "fallback_actions": {
            name: "idle"
            for name in (
                "walk",
                "sit",
                "sleep",
                "wave",
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
                "path": "frame.png",
                "size": len(frame),
                "sha256": hashlib.sha256(frame).hexdigest(),
            }
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("frame.png", frame)
        if unsafe_name:
            archive.writestr(unsafe_name, b"escape")
    return output.getvalue()


def _create_version(client: TestClient, creator_auth: dict[str, str]) -> tuple[str, str]:
    template = client.post(
        "/api/v1/admin/pet-templates",
        headers=creator_auth,
        json={
            "template_code": "official.cat.white",
            "display_name": "小白猫",
            "species": "cat",
            "description": "官方白猫模板",
        },
    )
    assert template.status_code == 201, template.text
    version = client.post(
        f"/api/v1/admin/pet-templates/{template.json()['id']}/versions",
        headers=creator_auth,
        json={
            "template_version": "1.1.0",
            "identity_version": "1.0.0",
            "asset_version": "2.0.0",
        },
    )
    assert version.status_code == 201, version.text
    return template.json()["id"], version.json()["id"]


def test_non_admin_cannot_manage_pet_templates(
    client: TestClient, account_auth: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/admin/pet-templates",
        headers=account_auth,
        json={
            "template_code": "official.denied",
            "display_name": "无权限",
            "species": "cat",
        },
    )
    assert response.status_code == 403


def test_reviewed_publish_flow_exposes_immutable_public_package(client: TestClient) -> None:
    creator = register_account(client, "admin_creator", display_name="编辑管理员")
    reviewer = register_account(client, "admin_reviewer", display_name="审核管理员")
    _template_id, version_id = _create_version(client, creator)

    uploaded = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/package",
        headers=creator,
        files={"package": ("pet.zip", _package_bytes(), "application/zip")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["package_sha256"]
    assert uploaded.json()["status"] == "draft"

    submitted = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/submit-review",
        headers=creator,
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "in_review"

    self_review = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/approve",
        headers=creator,
        json={"comment": "自己批准"},
    )
    assert self_review.status_code == 409

    approved = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/approve",
        headers=reviewer,
        json={"comment": "内容与技术检查通过"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    published = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/publish",
        headers=creator,
    )
    assert published.status_code == 201, published.text
    metadata = published.json()
    assert metadata["template_id"] == "official.cat.white"
    assert metadata["identity_version"] == "1.0.0"
    assert metadata["asset_version"] == "2.0.0"
    assert metadata["download_url"].startswith("/api/v1/assets/releases/")

    catalog = client.get(
        "/api/v1/catalog/pet-assets",
        params={
            "template_id": "official.cat.white",
            "identity_version": "1.0.0",
            "asset_version": "2.0.0",
        },
    )
    assert catalog.status_code == 200
    assert catalog.json() == metadata

    package = client.get(metadata["download_url"])
    assert package.status_code == 200
    assert package.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert hashlib.sha256(package.content).hexdigest() == metadata["package_sha256"]
    assert len(package.content) == metadata["package_size"]

    replace_after_publish = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/package",
        headers=creator,
        files={"package": ("pet.zip", _package_bytes(), "application/zip")},
    )
    assert replace_after_publish.status_code == 409

    repeated_publish = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/publish",
        headers=creator,
    )
    assert repeated_publish.status_code == 409

    with client.app.state.session_factory() as session:
        version = session.get(PetTemplateVersion, version_id)
        assert version is not None and version.status == "published"
        assert session.scalar(select(PetAssetRelease)) is not None
        actions = list(session.scalars(select(AdminAuditLog.action)))
        assert "pet_asset_package.uploaded" in actions
        assert "pet_template_version.approved" in actions
        assert "pet_template_version.published" in actions


def test_package_validation_rejects_zip_slip_and_identity_mismatch(client: TestClient) -> None:
    creator = register_account(client, "admin_creator")
    _template_id, version_id = _create_version(client, creator)

    unsafe = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/package",
        headers=creator,
        files={"package": ("unsafe.zip", _package_bytes(unsafe_name="../escape.txt"), "application/zip")},
    )
    assert unsafe.status_code == 422
    assert "安全的包内相对路径" in unsafe.json()["detail"]

    mismatch = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/package",
        headers=creator,
        files={
            "package": (
                "wrong.zip",
                _package_bytes(template_id="official.cat.other"),
                "application/zip",
            )
        },
    )
    assert mismatch.status_code == 422
    assert "不匹配" in mismatch.json()["detail"]
