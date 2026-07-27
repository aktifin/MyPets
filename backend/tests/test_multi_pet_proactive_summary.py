from __future__ import annotations

from fastapi.testclient import TestClient

from mypets_backend.models import Pet


def _create_pet(
    client: TestClient,
    auth: dict[str, str],
    *,
    key: str,
    name: str,
) -> str:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": key},
        json={
            "name": name,
            "template_id": "official.cat.multi-proactive",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["pet_id"])


def test_multiple_pet_notices_use_one_rate_limited_summary(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    first_id = _create_pet(
        client,
        account_auth,
        key="multi-proactive-first",
        name="团子",
    )
    second_id = _create_pet(
        client,
        account_auth,
        key="multi-proactive-second",
        name="豆包",
    )
    with client.app.state.session_factory() as session:
        first = session.get(Pet, first_id)
        second = session.get(Pet, second_id)
        assert first is not None and second is not None
        first.hunger = 18
        first.energy = 90
        first.cleanliness = 90
        first.mood = 90
        first.health = 95
        first.boredom = 0
        second.cleanliness = 20
        second.hunger = 90
        second.energy = 90
        second.mood = 90
        second.health = 95
        second.boredom = 0
        session.commit()

    preferences = client.patch(
        "/api/v1/portal/proactive-care/preferences",
        headers=account_auth,
        json={"quiet_hours_enabled": False, "min_interval_minutes": 15},
    )
    assert preferences.status_code == 200, preferences.text

    evaluated = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "timezone_offset_minutes": -480},
    )
    assert evaluated.status_code == 200, evaluated.text
    notice = evaluated.json()["notice"]
    assert notice is not None
    assert notice["kind"] == "low_state"
    assert notice["notice_key"].startswith("multi-pet:")
    assert notice["title"] == "2 只宠物需要你留意"
    assert "团子" in notice["detail"]
    assert "豆包" in notice["detail"]
    assert notice["pet_id"] is None
    assert notice["care_action"] is None
    assert notice["action_label"] == "查看多宠总览"
    assert notice["target_section"] == "dashboard-section"

    restored = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "timezone_offset_minutes": -480},
    )
    assert restored.status_code == 200
    assert restored.json()["notice"]["notice_key"] == notice["notice_key"]

    acknowledged = client.post(
        "/api/v1/portal/proactive-care/acknowledge",
        headers=account_auth,
        json={
            "notice_key": notice["notice_key"],
            "outcome": "opened",
            "timezone_offset_minutes": -480,
        },
    )
    assert acknowledged.status_code == 200, acknowledged.text

    rate_limited = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "desktop", "timezone_offset_minutes": -480},
    )
    assert rate_limited.status_code == 200
    assert rate_limited.json()["notice"] is None


def test_one_pet_notice_keeps_its_direct_action(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet_id = _create_pet(
        client,
        account_auth,
        key="single-proactive-pet",
        name="奶糖",
    )
    with client.app.state.session_factory() as session:
        pet = session.get(Pet, pet_id)
        assert pet is not None
        pet.hunger = 15
        pet.energy = 90
        pet.cleanliness = 90
        pet.mood = 90
        pet.health = 95
        pet.boredom = 0
        session.commit()

    preferences = client.patch(
        "/api/v1/portal/proactive-care/preferences",
        headers=account_auth,
        json={"quiet_hours_enabled": False},
    )
    assert preferences.status_code == 200
    result = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "pet_id": pet_id},
    )
    assert result.status_code == 200, result.text
    notice = result.json()["notice"]
    assert notice["pet_id"] == pet_id
    assert notice["care_action"] == "feed"
    assert notice["action_label"] == "去投喂"
