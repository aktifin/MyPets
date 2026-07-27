from __future__ import annotations

from fastapi.testclient import TestClient

from mypets_backend.models import Pet


def _create_pet(
    client: TestClient,
    auth: dict[str, str],
    *,
    name: str,
    key: str,
) -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": key},
        json={
            "name": name,
            "template_id": "official.cat.white",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_attention_rotates_for_review_without_auto_care(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    current = _create_pet(client, account_auth, name="当前宠物", key="multi-health-current")
    health = _create_pet(client, account_auth, name="康康", key="multi-health-review")
    with client.app.state.session_factory() as session:
        health_pet = session.get(Pet, health["pet_id"])
        assert health_pet is not None
        health_pet.health = 24
        health_pet.hunger = 95
        health_pet.energy = 95
        health_pet.cleanliness = 95
        health_pet.mood = 95
        health_pet.boredom = 5
        session.commit()

    selected = client.patch(
        "/api/v1/portal/preference",
        headers=account_auth,
        json={"selected_pet_id": current["pet_id"]},
    )
    assert selected.status_code == 200, selected.text

    response = client.get("/api/v1/multi-pet-overview", headers=account_auth)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["next_pet_id"] == health["pet_id"]
    item = next(item for item in payload["items"] if item["pet_id"] == health["pet_id"])
    assert item["priority"] == "urgent"
    assert item["recommended_action"] is None
    assert item["recommended_action_label"] == "查看状态"
    assert item["action_available"] is False
    assert item["switch_candidate"] is True
    assert "不会自动执行照料" in item["action_reason"]
    assert payload["care_ready_count"] == 1
