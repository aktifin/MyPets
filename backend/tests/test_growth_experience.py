from __future__ import annotations

from fastapi.testclient import TestClient

from mypets_backend.growth_experience import build_growth_progress, stage_label
from mypets_backend.models import Pet

from .test_pet_care import _bind_device, _create_pet, _register_account


def test_growth_experience_explains_next_stage_and_builds_memories(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet_id = _create_pet(client, account_auth, key="growth-experience-pet")["pet_id"]
    with client.app.state.session_factory() as session:
        pet = session.get(Pet, pet_id)
        assert pet is not None
        pet.growth_exp = 196
        pet.growth_level = 2
        pet.growth_stage = "newborn"
        pet.bond_exp = 79
        pet.bond_level = 1
        session.commit()

    cared = client.post(
        f"/api/v1/pets/{pet_id}/interactions/play",
        headers={**account_auth, "Idempotency-Key": "growth-experience-play"},
        json={},
    )
    assert cared.status_code == 200, cared.text
    assert cared.json()["pet"]["stats"]["growth_level"] == 3
    assert cared.json()["pet"]["stats"]["growth_stage"] == "child"
    assert cared.json()["pet"]["stats"]["bond_level"] == 2

    response = client.get(
        f"/api/v1/pets/{pet_id}/growth-experience?limit=20",
        headers=account_auth,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    progress = data["progress"]
    assert progress["current_stage"] == "child"
    assert progress["current_stage_label"] == "幼年期"
    assert progress["next_stage"] == "adult"
    assert progress["next_stage_label"] == "成熟期"
    assert progress["next_stage_target_level"] == 7
    assert progress["next_stage_exp_remaining"] == 397
    assert progress["growth_exp_remaining"] == 97
    assert progress["bond_exp_remaining"] == 77
    assert progress["suggested_action"] == "play"
    assert progress["estimated_actions"] == 57
    assert progress["final_stage"] is False

    memory_types = [item["memory_type"] for item in data["memories"]]
    assert memory_types[:3] == ["growth_stage", "bond_level", "growth_level"]
    assert memory_types[-1] == "adoption"
    stage_memory = data["memories"][0]
    assert stage_memory["title"] == "进入幼年期"
    assert "初生期" in stage_memory["detail"]
    assert stage_memory["source_label"] == "日常照料"
    assert data["settled_at"]


def test_growth_experience_is_visible_to_bound_device_and_account_scoped(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet_id = _create_pet(client, account_auth, key="growth-device-pet")["pet_id"]
    _device, device_auth, _secret = _bind_device(
        client,
        account_auth,
        public_id="growth-device-0001",
        name="成长记录电脑",
    )
    visible = client.get(
        f"/api/v1/pets/{pet_id}/growth-experience",
        headers=device_auth,
    )
    assert visible.status_code == 200, visible.text
    assert visible.json()["memories"][0]["memory_type"] == "adoption"

    other_auth = _register_account(client, "growth_experience_other")
    denied = client.get(
        f"/api/v1/pets/{pet_id}/growth-experience",
        headers=other_auth,
    )
    assert denied.status_code == 404


def test_final_stage_keeps_level_and_bond_goals_without_false_pressure() -> None:
    pet = {
        "growth_level": 7,
        "growth_exp": 645,
        "bond_level": 4,
        "bond_exp": 250,
        "growth_stage": "adult",
    }
    progress = build_growth_progress(pet)
    assert progress.final_stage is True
    assert progress.current_stage_label == "成熟期"
    assert progress.next_stage is None
    assert progress.stage_progress_percent == 100
    assert progress.growth_exp_remaining == 55
    assert progress.bond_exp_remaining == 70
    assert "没有终点" not in progress.detail
    assert stage_label("newborn") == "初生期"
    assert stage_label("child") == "幼年期"
    assert stage_label("adult") == "成熟期"
