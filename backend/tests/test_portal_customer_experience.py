from __future__ import annotations

from fastapi.testclient import TestClient

from .test_user_portal import _register_account


def test_customer_experience_assets_are_injected_and_not_cached(client: TestClient) -> None:
    page = client.get("/portal")
    assert page.status_code == 200
    assert "/portal/customer-experience.css" in page.text
    assert "/portal/customer-experience.js" in page.text

    script = client.get("/portal/customer-experience.js")
    styles = client.get("/portal/customer-experience.css")
    assert script.status_code == 200
    assert styles.status_code == 200
    assert script.headers["cache-control"] == "no-store"
    assert styles.headers["cache-control"] == "no-store"
    assert "/api/v1/portal/pet-presets" in script.text
    assert "pet-onboarding-dialog" in script.text
    assert "legacyForm.hidden = true" in script.text
    assert "portal-pet-switcher" in script.text
    assert "现在最需要" in script.text
    assert "style=" not in script.text


def test_pet_presets_hide_internal_version_selection_from_customers(client: TestClient) -> None:
    unauthenticated = client.get("/api/v1/portal/pet-presets")
    assert unauthenticated.status_code == 401

    auth = _register_account(client, "customer_experience_owner", display_name="体验用户")
    response = client.get("/api/v1/portal/pet-presets", headers=auth)

    assert response.status_code == 200, response.text
    presets = response.json()
    assert presets
    starter = presets[0]
    assert starter["display_name"] == "云朵白猫"
    assert starter["source"] == "bundled"
    assert starter["icon"] == "🐱"
    assert starter["template_id"] == "official.cat.white"
    assert starter["template_version"] == "1.0.0"
    assert starter["identity_version"] == "1.0.0"
    assert starter["asset_version"] == "1.0.0"
