from __future__ import annotations

from fastapi.testclient import TestClient


def test_user_portal_serves_asset_production_workspace(client: TestClient) -> None:
    page = client.get("/portal")
    assert page.status_code == 200, page.text
    submission_script = '<script src="/portal/asset-submissions.js" defer></script>'
    production_script = '<script src="/portal/asset-production.js" defer></script>'
    assert submission_script in page.text
    assert production_script in page.text
    assert page.text.index(submission_script) < page.text.index(production_script)
    assert page.headers["cache-control"] == "no-store"

    script = client.get("/portal/asset-production.js")
    assert script.status_code == 200, script.text
    assert "pet-asset-production-jobs" in script.text
    assert "reference-images" in script.text
    assert "sessionStorage" not in script.text
    assert script.headers["x-content-type-options"] == "nosniff"


def test_admin_console_serves_asset_production_workspace(client: TestClient) -> None:
    page = client.get("/admin")
    assert page.status_code == 200, page.text
    submission_script = '<script src="/admin/asset-submissions.js" defer></script>'
    production_script = '<script src="/admin/asset-production.js" defer></script>'
    assert submission_script in page.text
    assert production_script in page.text
    assert page.text.index(submission_script) < page.text.index(production_script)
    assert "object-src 'none'" in page.headers["content-security-policy"]

    script = client.get("/admin/asset-production.js")
    assert script.status_code == 200, script.text
    assert "target_template_version_id" in script.text
    assert "上传成功后产物不可静默替换" in script.text
    assert "不会自动发布" in script.text
    assert "/publish" not in script.text
    assert "Authorization: `Bearer ${state.token}`" in script.text
    assert script.headers["cache-control"] == "no-store"
