from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from mypets_backend.models import Pet, SyncEvent
from mypets_backend.proactive_care import build_proactive_candidates, in_quiet_hours


def _create_pet(client: TestClient, auth: dict[str, str], *, key: str = "proactive-pet") -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": key},
        json={
            "name": "团子",
            "template_id": "official.cat.proactive",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _bind_device(client: TestClient, auth: dict[str, str]) -> dict[str, str]:
    bound = client.post(
        "/api/v1/devices/bind",
        headers=auth,
        json={"public_id": "proactive-device-0001", "name": "主动关怀测试电脑", "platform": "windows"},
    )
    assert bound.status_code == 201, bound.text
    token = client.post(
        "/api/v1/auth/device-token",
        json={
            "device_id": bound.json()["device"]["id"],
            "device_secret": bound.json()["device_secret"],
        },
    )
    assert token.status_code == 200, token.text
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _disable_quiet_hours(client: TestClient, auth: dict[str, str]) -> None:
    response = client.patch(
        "/api/v1/portal/proactive-care/preferences",
        headers=auth,
        json={"quiet_hours_enabled": False},
    )
    assert response.status_code == 200, response.text


def test_preferences_default_patch_and_device_visibility(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    defaults = client.get("/api/v1/portal/proactive-care/preferences", headers=account_auth)
    assert defaults.status_code == 200
    assert defaults.json() == {
        "enabled": True,
        "low_state_enabled": True,
        "inactivity_enabled": True,
        "reminder_enabled": True,
        "quiet_hours_enabled": True,
        "quiet_start": "22:00",
        "quiet_end": "08:00",
        "min_interval_minutes": 120,
        "max_daily_notices": 3,
    }

    updated = client.patch(
        "/api/v1/portal/proactive-care/preferences",
        headers=account_auth,
        json={
            "quiet_start": "21:30",
            "quiet_end": "07:15",
            "min_interval_minutes": 180,
            "max_daily_notices": 2,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["quiet_start"] == "21:30"
    assert updated.json()["min_interval_minutes"] == 180

    device_auth = _bind_device(client, account_auth)
    visible = client.get("/api/v1/portal/proactive-care/preferences", headers=device_auth)
    assert visible.status_code == 200
    assert visible.json() == updated.json()


def test_low_state_notice_restores_on_same_surface_but_other_surface_is_rate_limited(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet_id = _create_pet(client, account_auth)["pet_id"]
    _disable_quiet_hours(client, account_auth)
    with client.app.state.session_factory() as session:
        pet = session.get(Pet, pet_id)
        assert pet is not None
        pet.hunger = 20
        pet.energy = 90
        pet.cleanliness = 90
        pet.mood = 90
        pet.boredom = 0
        session.commit()

    first = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "pet_id": pet_id, "timezone_offset_minutes": -480},
    )
    assert first.status_code == 200, first.text
    notice = first.json()["notice"]
    assert notice["kind"] == "low_state"
    assert notice["pet_id"] == pet_id
    assert notice["care_action"] == "feed"
    assert notice["action_label"] == "去投喂"
    assert "有点饿" in notice["title"]

    restored = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "pet_id": pet_id, "timezone_offset_minutes": -480},
    )
    assert restored.status_code == 200
    assert restored.json()["notice"]["notice_key"] == notice["notice_key"]
    assert restored.json()["notice"]["delivered_at"] == notice["delivered_at"]

    other_surface = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "desktop", "pet_id": pet_id, "timezone_offset_minutes": -480},
    )
    assert other_surface.status_code == 200
    assert other_surface.json()["notice"] is None
    assert "上一条" in other_surface.json()["suppression_reason"]

    with client.app.state.session_factory() as session:
        deliveries = list(
            session.scalars(
                select(SyncEvent).where(
                    SyncEvent.event_type == "proactive_care_notice_delivered"
                )
            )
        )
        assert len(deliveries) == 1


def test_quiet_hours_and_global_disable_suppress_evaluation(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet_id = _create_pet(client, account_auth, key="proactive-quiet-pet")["pet_id"]
    quiet = client.patch(
        "/api/v1/portal/proactive-care/preferences",
        headers=account_auth,
        json={"quiet_hours_enabled": True, "quiet_start": "00:00", "quiet_end": "00:00"},
    )
    assert quiet.status_code == 200
    result = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "pet_id": pet_id, "timezone_offset_minutes": 0},
    )
    assert result.status_code == 200
    assert result.json()["notice"] is None
    assert result.json()["suppression_reason"] == "当前处于免打扰时段"

    disabled = client.patch(
        "/api/v1/portal/proactive-care/preferences",
        headers=account_auth,
        json={"enabled": False, "quiet_hours_enabled": False},
    )
    assert disabled.status_code == 200
    result = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "pet_id": pet_id},
    )
    assert result.json()["suppression_reason"] == "主动关怀已关闭"


def test_dismiss_today_survives_delivery_interval_expiry(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet_id = _create_pet(client, account_auth, key="proactive-dismiss-pet")["pet_id"]
    with client.app.state.session_factory() as session:
        pet = session.get(Pet, pet_id)
        assert pet is not None
        pet.mood = 20
        session.commit()

    client.patch(
        "/api/v1/portal/proactive-care/preferences",
        headers=account_auth,
        json={"min_interval_minutes": 15, "quiet_hours_enabled": False},
    )
    first = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "pet_id": pet_id},
    )
    assert first.status_code == 200
    notice_key = first.json()["notice"]["notice_key"]
    ack = client.post(
        "/api/v1/portal/proactive-care/acknowledge",
        headers=account_auth,
        json={"notice_key": notice_key, "outcome": "dismissed_today", "timezone_offset_minutes": 0},
    )
    assert ack.status_code == 200
    suppress_until = datetime.fromisoformat(ack.json()["suppress_until"].replace("Z", "+00:00"))
    assert suppress_until > datetime.now(UTC)

    with client.app.state.session_factory() as session:
        delivered = session.scalar(
            select(SyncEvent)
            .where(SyncEvent.event_type == "proactive_care_notice_delivered")
            .order_by(SyncEvent.sequence.desc())
        )
        assert delivered is not None
        delivered.created_at = datetime.now(UTC) - timedelta(hours=2)
        session.commit()

    again = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "pet_id": pet_id},
    )
    assert again.status_code == 200
    assert again.json()["notice"] is None
    assert again.json()["suppression_reason"] == "暂无新的关怀提示"


def test_due_reminder_is_a_candidate_without_a_pet(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    _disable_quiet_hours(client, account_auth)
    created = client.post(
        "/api/v1/reminders/occurrences",
        headers={**account_auth, "Idempotency-Key": "proactive-due-reminder"},
        json={
            "source": "myreminder",
            "source_reminder_id": "proactive-due-001",
            "title": "准备猫粮",
            "content": "检查今天的猫粮",
            "scheduled_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
            "timezone": "Asia/Shanghai",
            "priority": "normal",
            "category": "pet_care",
            "version": 1,
        },
    )
    assert created.status_code == 201, created.text
    evaluated = client.post(
        "/api/v1/portal/proactive-care/evaluate",
        headers=account_auth,
        json={"surface": "web", "timezone_offset_minutes": -480},
    )
    assert evaluated.status_code == 200, evaluated.text
    notice = evaluated.json()["notice"]
    assert notice["kind"] == "reminder_due"
    assert notice["title"] == "准备猫粮"
    assert notice["target_section"] == "reminders-section"


def test_pure_rules_are_gentle_role_scoped_and_timezone_aware() -> None:
    now = datetime(2026, 7, 26, 13, 30, tzinfo=UTC)
    pets = [
        {
            "id": "pet-owner",
            "name": "团子",
            "presence": "home",
            "hunger": 25,
            "energy": 80,
            "cleanliness": 80,
            "mood": 80,
            "health": 100,
            "boredom": 0,
            "created_at": now - timedelta(days=2),
        },
        {
            "id": "pet-viewer",
            "name": "只读宠物",
            "presence": "home",
            "hunger": 1,
            "created_at": now - timedelta(days=2),
        },
    ]
    candidates = build_proactive_candidates(
        pets=pets,
        relations={"pet-owner": {"role": "owner"}, "pet-viewer": {"role": "viewer"}},
        last_interactions={"pet-owner": now - timedelta(hours=13)},
        reminders=[],
        preferences=None,
        now=now,
    )
    assert {item["pet_id"] for item in candidates} == {"pet-owner"}
    assert any("有点饿" in item["title"] for item in candidates)
    assert all("危险" not in json.dumps(item, ensure_ascii=False) for item in candidates)
    assert in_quiet_hours(
        now=now,
        timezone_offset_minutes=-480,
        quiet_start="21:00",
        quiet_end="08:00",
    ) is True
