from __future__ import annotations

from fastapi.testclient import TestClient

from .test_user_portal import _register_account


def test_customer_experience_assets_are_injected_and_not_cached(client: TestClient) -> None:
    page = client.get("/portal")
    assert page.status_code == 200
    assert "/portal/customer-experience.css" in page.text
    assert "/portal/customer-experience.js" in page.text
    assert "/portal/daily-care-experience.css" in page.text
    assert "/portal/daily-care-experience.js" in page.text
    assert "/portal/proactive-care-experience.css" in page.text
    assert "/portal/proactive-care-experience.js" in page.text
    assert "/portal/growth-experience.css" in page.text
    assert "/portal/growth-experience.js" in page.text

    script = client.get("/portal/customer-experience.js")
    styles = client.get("/portal/customer-experience.css")
    daily_script = client.get("/portal/daily-care-experience.js")
    daily_styles = client.get("/portal/daily-care-experience.css")
    proactive_script = client.get("/portal/proactive-care-experience.js")
    proactive_styles = client.get("/portal/proactive-care-experience.css")
    growth_script = client.get("/portal/growth-experience.js")
    growth_styles = client.get("/portal/growth-experience.css")
    for response in (
        script,
        styles,
        daily_script,
        daily_styles,
        proactive_script,
        proactive_styles,
        growth_script,
        growth_styles,
    ):
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"

    assert "/api/v1/portal/pet-presets" in script.text
    assert "pet-onboarding-dialog" in script.text
    assert "legacyForm.hidden = true" in script.text
    assert "portal-pet-switcher" in script.text
    assert "现在最需要" in script.text
    assert "addButton.hidden = true" in script.text
    assert "logoutWithCustomerExperience" in script.text
    assert "请先登录后再添加宠物" in script.text

    assert "/daily-care?timezone_offset_minutes=" in daily_script.text
    assert "今天还需要做什么" in daily_script.text
    assert "今日陪伴徽章" in daily_script.text
    assert "remaining_seconds" in daily_script.text
    assert "daily_limit_reached" in daily_script.text

    assert "/api/v1/portal/proactive-care/preferences" in proactive_script.text
    assert "/api/v1/portal/proactive-care/evaluate" in proactive_script.text
    assert "/api/v1/portal/proactive-care/acknowledge" in proactive_script.text
    assert "主动关怀与免打扰" in proactive_script.text
    assert "今天不再提示" in proactive_script.text
    assert "稍后提醒" in proactive_script.text
    assert "不会替你自动操作" in proactive_script.text
    assert "ensureProactiveSelectValue" in proactive_script.text

    assert "/growth-experience?limit=30" in growth_script.text
    assert "下一步成长目标" in growth_script.text
    assert "成长纪念册" in growth_script.text
    assert "next_stage_target_level" in growth_script.text
    assert "stage_progress_percent" in growth_script.text
    assert "growth_exp_remaining" in growth_script.text

    assert "style=" not in script.text
    assert "style=" not in daily_script.text
    assert "style=" not in proactive_script.text
    assert "style=" not in growth_script.text


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
