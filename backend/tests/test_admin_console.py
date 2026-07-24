from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from .conftest import register_account
from .test_admin_publishing import _create_version, _package_bytes


def _spritesheet_package() -> bytes:
    sheet_buffer = io.BytesIO()
    sheet = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    sheet.paste((255, 0, 0, 255), (0, 0, 32, 32))
    sheet.paste((0, 0, 255, 255), (32, 0, 64, 32))
    sheet.save(sheet_buffer, format="PNG")
    manifest = {
        "schema_version": "2.1",
        "template_id": "official.cat.white",
        "identity_version": "1.0.0",
        "asset_version": "2.0.0",
        "renderer": {
            "kind": "spritesheet",
            "path": "sheet.png",
            "columns": 2,
            "rows": 1,
            "cell_width": 32,
            "cell_height": 32,
        },
        "animations": {
            "idle": [{"row": 0, "column": 0}, {"row": 0, "column": 1}]
        },
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
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("sheet.png", sheet_buffer.getvalue())
    return output.getvalue()


def test_admin_console_shell_has_restrictive_browser_headers(client: TestClient) -> None:
    page = client.get("/admin")
    assert page.status_code == 200
    assert "宠物内容管理台" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"

    script = client.get("/admin/app.js")
    styles = client.get("/admin/styles.css")
    assert script.status_code == 200
    assert styles.status_code == 200
    assert "sessionStorage" in script.text
    assert "access_token=" not in script.text
    assert "Authorization" in script.text
    assert "PetAsset" not in page.text


def test_console_lists_versions_and_renders_authenticated_preview(client: TestClient) -> None:
    creator = register_account(client, "admin_creator", display_name="编辑管理员")
    template_id, version_id = _create_version(client, creator)
    uploaded = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/package",
        headers=creator,
        files={"package": ("pet.zip", _package_bytes(), "application/zip")},
    )
    assert uploaded.status_code == 200, uploaded.text

    listed = client.get(
        "/api/v1/admin/pet-template-versions",
        headers=creator,
        params={"status": "draft", "template_id": template_id},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [version_id]

    unauthorized = client.get(
        f"/api/v1/admin/pet-template-versions/{version_id}/preview-image"
    )
    assert unauthorized.status_code == 401

    preview = client.get(
        f"/api/v1/admin/pet-template-versions/{version_id}/preview",
        headers=creator,
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["renderer_kind"] == "frames"
    assert payload["preview_image_url"].endswith(f"/{version_id}/preview-image")
    actions = {item["name"]: item for item in payload["actions"]}
    assert actions["idle"]["frame_count"] == 1
    assert actions["walk"]["source_action"] == "idle"
    assert actions["walk"]["fallback_to"] == "idle"

    image_response = client.get(
        payload["preview_image_url"],
        headers=creator,
        params={"action": "walk", "frame_index": 0},
    )
    assert image_response.status_code == 200, image_response.text
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.headers["cache-control"] == "no-store"
    with Image.open(io.BytesIO(image_response.content)) as image:
        assert image.size == (32, 32)
        assert image.mode == "RGBA"


def test_console_crops_requested_spritesheet_cell(client: TestClient) -> None:
    creator = register_account(client, "admin_creator")
    _template_id, version_id = _create_version(client, creator)
    uploaded = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/package",
        headers=creator,
        files={"package": ("sheet.zip", _spritesheet_package(), "application/zip")},
    )
    assert uploaded.status_code == 200, uploaded.text

    preview = client.get(
        f"/api/v1/admin/pet-template-versions/{version_id}/preview",
        headers=creator,
    )
    assert preview.status_code == 200
    assert preview.json()["renderer_kind"] == "spritesheet"

    frame = client.get(
        f"/api/v1/admin/pet-template-versions/{version_id}/preview-image",
        headers=creator,
        params={"action": "idle", "frame_index": 1},
    )
    assert frame.status_code == 200, frame.text
    with Image.open(io.BytesIO(frame.content)) as image:
        assert image.size == (32, 32)
        assert image.getpixel((16, 16)) == (0, 0, 255, 255)


def test_console_release_history_uses_published_immutable_releases(client: TestClient) -> None:
    creator = register_account(client, "admin_creator")
    reviewer = register_account(client, "admin_reviewer")
    _template_id, version_id = _create_version(client, creator)
    assert client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/package",
        headers=creator,
        files={"package": ("pet.zip", _package_bytes(), "application/zip")},
    ).status_code == 200
    assert client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/submit-review",
        headers=creator,
    ).status_code == 200
    assert client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/approve",
        headers=reviewer,
        json={"comment": "预览和动作矩阵检查通过"},
    ).status_code == 200
    published = client.post(
        f"/api/v1/admin/pet-template-versions/{version_id}/publish",
        headers=creator,
    )
    assert published.status_code == 201, published.text

    releases = client.get("/api/v1/admin/pet-asset-releases", headers=creator)
    assert releases.status_code == 200
    assert releases.json() == [published.json()]

    filtered = client.get(
        "/api/v1/admin/pet-asset-releases",
        headers=creator,
        params={"template_id": "official.cat.missing"},
    )
    assert filtered.status_code == 200
    assert filtered.json() == []
