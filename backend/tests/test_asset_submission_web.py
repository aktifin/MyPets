from __future__ import annotations

from fastapi.testclient import TestClient


def test_user_portal_includes_pet_submission_workspace(client: TestClient) -> None:
    page = client.get("/portal")
    assert page.status_code == 200, page.text
    assert '<script src="/portal/asset-submissions.js" defer></script>' in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "object-src 'none'" in page.headers["content-security-policy"]

    script = client.get("/portal/asset-submissions.js")
    assert script.status_code == 200, script.text
    assert "pet-asset-submissions" in script.text
    assert "rights_confirmed" in script.text
    assert script.headers["x-content-type-options"] == "nosniff"


def test_admin_console_includes_submission_review_workspace(client: TestClient) -> None:
    page = client.get("/admin")
    assert page.status_code == 200, page.text
    assert '<script src="/admin/asset-submissions.js" defer></script>' in page.text
    assert page.text.index("/admin/app.js") < page.text.index("/admin/asset-submissions.js")
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]

    script = client.get("/admin/asset-submissions.js")
    assert script.status_code == 200, script.text
    assert "start-review" in script.text
    assert "publication" not in script.text.lower()
    assert script.headers["x-content-type-options"] == "nosniff"
