from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from mypets_backend.daily_care import build_daily_care_summary


def _create_pet(client: TestClient, auth: dict[str, str], *, key: str) -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": key},
        json={
            "name": "小满",
            "template_id": "official.cat.daily",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _care(
    client: TestClient,
    auth: dict[str, str],
    pet_id: str,
    action: str,
    key: str,
) -> dict:
    response = client.post(
        f"/api/v1/pets/{pet_id}/interactions/{action}",
        headers={**auth, "Idempotency-Key": key},
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_daily_care_endpoint_tracks_tasks_reward_and_cooldown(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet_id = _create_pet(client, account_auth, key="daily-care-pet")["pet_id"]
    _care(client, account_auth, pet_id, "feed", "daily-feed")
    _care(client, account_auth, pet_id, "play", "daily-play")
    _care(client, account_auth, pet_id, "clean", "daily-clean")

    response = client.get(
        f"/api/v1/pets/{pet_id}/daily-care?timezone_offset_minutes=-480",
        headers=account_auth,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pet_id"] == pet_id
    assert data["completed_tasks"] == 3
    assert data["total_tasks"] == 3
    assert data["all_tasks_completed"] is True
    assert data["streak_days"] == 1
    assert data["reward_title"] == "今日陪伴徽章"
    assert data["care_count"] == 3
    assert data["daily_remaining"] == 47
    tasks = {item["task_id"]: item for item in data["tasks"]}
    assert tasks["care-three-times"]["current"] == 3
    assert tasks["care-two-types"]["current"] == 2
    assert tasks["bond-once"]["current"] == 1
    actions = {item["action"]: item for item in data["actions"]}
    assert actions["feed"]["available"] is False
    assert actions["feed"]["remaining_seconds"] >= 1
    assert "秒后" in actions["feed"]["reason"]
    assert actions["pet"]["available"] is True


def test_daily_care_endpoint_requires_pet_membership(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    response = client.get(
        "/api/v1/pets/not-my-pet/daily-care",
        headers=account_auth,
    )
    assert response.status_code == 404


def test_streak_keeps_yesterday_until_today_ends() -> None:
    now = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    records: list[dict[str, str]] = []
    for days_ago in (1, 2):
        created = now - timedelta(days=days_ago)
        for action in ("feed", "play", "clean"):
            records.append({"action": action, "created_at": created.isoformat()})
    records.append({"action": "pet", "created_at": now.isoformat()})

    summary = build_daily_care_summary(
        records,
        pet_id="pet-1",
        now=now,
        timezone_offset_minutes=0,
    )

    assert summary["all_tasks_completed"] is False
    assert summary["completed_tasks"] == 1
    assert summary["streak_days"] == 2
    assert summary["reward_detail"] == "还剩 2 项任务，今天结束前都可以完成。"


def test_timezone_offset_changes_the_local_task_day() -> None:
    now = datetime(2026, 7, 26, 0, 30, tzinfo=UTC)
    record = {
        "action": "feed",
        "created_at": (now - timedelta(hours=1)).isoformat(),
    }

    utc_summary = build_daily_care_summary(
        [record], pet_id="pet-1", now=now, timezone_offset_minutes=0
    )
    china_summary = build_daily_care_summary(
        [record], pet_id="pet-1", now=now, timezone_offset_minutes=-480
    )

    assert utc_summary["care_count"] == 0
    assert china_summary["care_count"] == 1
