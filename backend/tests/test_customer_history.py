from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from mypets_backend.models import Account, Pet, SyncEvent
from mypets_backend.reminder_models import ReminderOccurrence
from mypets_backend.social_models import CaregiverInvitation, FriendRequest
from mypets_backend.visit_models import PetVisit

from .conftest import bind_device, register_account


def _account_id(client: TestClient, username: str) -> str:
    with client.app.state.session_factory() as session:
        value = session.scalar(select(Account).where(Account.username == username))
        assert value is not None
        return value.id


def _reminder_event(
    *,
    account_id: str,
    occurrence: ReminderOccurrence,
    event_type: str,
    occurred_at: datetime,
    snooze_minutes: int | None = None,
) -> SyncEvent:
    return SyncEvent(
        event_id=str(uuid4()),
        account_id=account_id,
        event_type=event_type,
        idempotency_key=f"history:{event_type}:{uuid4()}",
        payload_json=json.dumps(
            {
                "action": event_type.removeprefix("reminder_"),
                "snooze_minutes": snooze_minutes,
                "occurrence": {
                    "occurrence_id": occurrence.id,
                    "title": occurrence.title,
                    "content": occurrence.content,
                    "state": occurrence.state,
                    "scheduled_at": occurrence.scheduled_at.isoformat(),
                },
            }
        ),
        created_at=occurred_at,
    )


def _seed_history(client: TestClient) -> dict[str, object]:
    owner_auth = register_account(client, "history_owner", display_name="主人")
    friend_auth = register_account(client, "history_friend", display_name="好友")
    stranger_auth = register_account(client, "history_stranger", display_name="无关用户")
    owner_id = _account_id(client, "history_owner")
    friend_id = _account_id(client, "history_friend")
    now = datetime.now(UTC)
    owner_pet_id = str(uuid4())
    friend_pet_id = str(uuid4())
    completed_reminder_id = str(uuid4())
    dismissed_reminder_id = str(uuid4())
    visit_id = str(uuid4())

    with client.app.state.session_factory() as session:
        session.add_all(
            [
                Pet(
                    id=owner_pet_id,
                    name="小白",
                    template_id="official.cat.white",
                    template_version="1.0.0",
                    identity_version="1.0.0",
                    primary_owner_account_id=owner_id,
                    asset_version="1.0.0",
                ),
                Pet(
                    id=friend_pet_id,
                    name="团子",
                    template_id="official.cat.orange",
                    template_version="1.0.0",
                    identity_version="1.0.0",
                    primary_owner_account_id=friend_id,
                    asset_version="1.0.0",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                FriendRequest(
                    id=str(uuid4()),
                    sender_account_id=friend_id,
                    recipient_account_id=owner_id,
                    status="accepted",
                    created_at=now - timedelta(days=41),
                    responded_at=now - timedelta(days=40),
                ),
                FriendRequest(
                    id=str(uuid4()),
                    sender_account_id=owner_id,
                    recipient_account_id=friend_id,
                    status="rejected",
                    created_at=now - timedelta(days=3),
                    responded_at=now - timedelta(days=2),
                ),
                CaregiverInvitation(
                    id=str(uuid4()),
                    pet_id=friend_pet_id,
                    invited_account_id=owner_id,
                    invited_by_account_id=friend_id,
                    role="caregiver",
                    status="accepted",
                    created_at=now - timedelta(days=2),
                    responded_at=now - timedelta(days=1, hours=12),
                ),
                PetVisit(
                    id=visit_id,
                    requester_account_id=owner_id,
                    host_account_id=friend_id,
                    visitor_pet_id=owner_pet_id,
                    host_pet_id=friend_pet_id,
                    status="completed",
                    note="一起玩",
                    duration_minutes=60,
                    completion_reason="visit_auto_returned",
                    created_at=now - timedelta(hours=8),
                    responded_at=now - timedelta(hours=7, minutes=55),
                    started_at=now - timedelta(hours=7, minutes=55),
                    scheduled_end_at=now - timedelta(hours=6, minutes=55),
                    completed_at=now - timedelta(hours=6, minutes=55),
                ),
            ]
        )
        completed = ReminderOccurrence(
            id=completed_reminder_id,
            account_id=owner_id,
            source="mypets",
            source_reminder_id="completed-reminder",
            title="给小白喂食",
            content="完成今天的喂食。",
            scheduled_at=now - timedelta(hours=6),
            timezone="Asia/Shanghai",
            state="completed",
            snooze_count=2,
            completed_at=now - timedelta(hours=4),
            created_at=now - timedelta(hours=7),
            updated_at=now - timedelta(hours=4),
        )
        dismissed = ReminderOccurrence(
            id=dismissed_reminder_id,
            account_id=owner_id,
            source="mypets",
            source_reminder_id="dismissed-reminder",
            title="整理宠物相册",
            content="本次不需要处理。",
            scheduled_at=now - timedelta(hours=3),
            timezone="Asia/Shanghai",
            state="dismissed",
            dismissed_at=now - timedelta(hours=2),
            created_at=now - timedelta(hours=4),
            updated_at=now - timedelta(hours=2),
        )
        session.add_all([completed, dismissed])
        session.flush()
        session.add_all(
            [
                _reminder_event(
                    account_id=owner_id,
                    occurrence=completed,
                    event_type="reminder_snoozed",
                    occurred_at=now - timedelta(hours=6),
                    snooze_minutes=10,
                ),
                _reminder_event(
                    account_id=owner_id,
                    occurrence=completed,
                    event_type="reminder_snoozed",
                    occurred_at=now - timedelta(hours=5),
                    snooze_minutes=30,
                ),
                _reminder_event(
                    account_id=owner_id,
                    occurrence=completed,
                    event_type="reminder_completed",
                    occurred_at=now - timedelta(hours=4),
                ),
                _reminder_event(
                    account_id=owner_id,
                    occurrence=dismissed,
                    event_type="reminder_dismissed",
                    occurred_at=now - timedelta(hours=2),
                ),
            ]
        )
        session.commit()

    return {
        "owner_auth": owner_auth,
        "friend_auth": friend_auth,
        "stranger_auth": stranger_auth,
        "owner_id": owner_id,
        "visit_id": visit_id,
        "completed_reminder_id": completed_reminder_id,
        "now": now,
    }


def test_customer_history_projects_actions_without_duplicate_terminal_reminders(client: TestClient) -> None:
    values = _seed_history(client)
    response = client.get("/api/v1/customer-history?days=30", headers=values["owner_auth"])
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 8
    actions = [item["action"] for item in payload["items"]]
    assert actions.count("snoozed") == 2
    assert actions.count("completed") == 1
    assert actions.count("dismissed") == 1
    assert actions.count("accepted") == 2
    assert actions.count("returned") == 1
    assert actions.count("rejected") == 1
    reminder_completion = [
        item
        for item in payload["items"]
        if item["target_id"] == values["completed_reminder_id"] and item["action"] == "completed"
    ]
    assert len(reminder_completion) == 1
    assert payload["items"][0]["action"] == "dismissed"


def test_customer_history_supports_kind_time_and_account_filters(client: TestClient) -> None:
    values = _seed_history(client)
    reminder = client.get(
        "/api/v1/customer-history?kind=reminder&days=30",
        headers=values["owner_auth"],
    )
    assert reminder.status_code == 200
    assert reminder.json()["count"] == 4
    assert {item["kind"] for item in reminder.json()["items"]} == {"reminder"}

    all_time = client.get(
        "/api/v1/customer-history?start=1970-01-01T00:00:00%2B00:00",
        headers=values["owner_auth"],
    )
    assert all_time.status_code == 200
    assert all_time.json()["count"] == 9
    assert any("接受了 好友 的好友申请" in item["title"] for item in all_time.json()["items"])

    recent_start = (values["now"] - timedelta(hours=5, minutes=30)).isoformat()
    recent = client.get(
        "/api/v1/customer-history",
        headers=values["owner_auth"],
        params={"start": recent_start, "kind": "reminder"},
    )
    assert recent.status_code == 200
    assert [item["action"] for item in recent.json()["items"]] == [
        "dismissed",
        "completed",
        "snoozed",
    ]

    stranger = client.get("/api/v1/customer-history?days=30", headers=values["stranger_auth"])
    assert stranger.status_code == 200
    assert stranger.json() == {"count": 0, "items": []}


def test_customer_history_accepts_device_token_for_same_account(client: TestClient) -> None:
    values = _seed_history(client)
    _device, device_auth, _secret = bind_device(
        client,
        values["owner_auth"],
        public_id="history-device-0001",
        name="历史记录测试设备",
    )
    response = client.get("/api/v1/customer-history?kind=visit&days=30", headers=device_auth)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 2
    assert {item["target_id"] for item in payload["items"]} == {values["visit_id"]}


def test_customer_history_validates_ranges_and_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/customer-history").status_code == 401
    auth = register_account(client, "history_validation", display_name="校验用户")
    invalid = client.get(
        "/api/v1/customer-history",
        headers=auth,
        params={
            "start": "2026-07-27T12:00:00+00:00",
            "end": "2026-07-27T11:00:00+00:00",
        },
    )
    assert invalid.status_code == 422
    assert "start 必须早于 end" in invalid.text
