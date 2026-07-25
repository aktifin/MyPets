from __future__ import annotations

from fastapi.testclient import TestClient


def test_phase1_portal_shell_restores_core_dom_and_has_no_inline_handlers(
    client: TestClient,
) -> None:
    page = client.get("/portal")
    assert page.status_code == 200, page.text
    assert "MyPets 用户中心" in page.text
    for element_id in (
        "auth-view",
        "app-view",
        "dashboard-section",
        "pets-section",
        "friends-section",
        "messages-section",
        "reminders-section",
        "visits-section",
        "account-section",
        "login-form",
        "pet-list",
        "conversation-list",
        "reminder-list",
    ):
        assert f'id="{element_id}"' in page.text
    assert 'src="/portal/phase1.js"' in page.text
    assert "onclick=" not in page.text
    assert "https://" not in page.text


def test_phase1_script_is_same_origin_and_uses_existing_authoritative_apis(
    client: TestClient,
) -> None:
    response = client.get("/portal/phase1.js")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "/api/v1/pets/${petId}/growth" in response.text
    assert "/api/v1/pets/${petId}/activity" in response.text
    assert "/api/v1/conversations?limit=100" in response.text
    assert "/api/v1/reminders/snapshot?limit=200" in response.text
    assert "personal-asset-deployment" in response.text
    assert "sessionStorage" not in response.text
    assert "localStorage" not in response.text


def test_phase1_styles_include_responsive_dashboard_and_message_layout(
    client: TestClient,
) -> None:
    response = client.get("/portal/styles.css")
    assert response.status_code == 200, response.text
    assert ".dashboard-grid" in response.text
    assert ".summary-grid" in response.text
    assert ".message-thread" in response.text
    assert "@media (max-width: 560px)" in response.text
