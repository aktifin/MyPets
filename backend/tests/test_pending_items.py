from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from .conftest import bind_device, register_account


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


def _make_friends(
    client: TestClient,
    sender_auth: dict[str, str],
    recipient_auth: dict[str, str],
    *,
    recipient_username: str,
) -> None:
    created = client.post(
        "/api/v1/friend-requests",
        headers=sender_auth,
        json={"username": recipient_username},
    )
    assert created.status_code == 201, created.text
    accepted = client.post(
        f"/api/v1/friend-requests/{created.json()['request_id']}/accept",
        headers=recipient_auth,
    )
    assert accepted.status_code == 200, accepted.text


def _seed_pending_items(
    client: TestClient,
    owner_auth: dict[str, str],
) -> dict[str, str]:
    friend_auth = register_account(
        client,
        "pending_friend",
        display_name="新朋友",
    )
    friend_request = client.post(
        "/api/v1/friend-requests",
        headers=friend_auth,
        json={"username": "owner_1"},
    )
    assert friend_request.status_code == 201, friend_request.text

    caregiver_auth = register_account(
        client,
        "pending_caregiver",
        display_name="共同照料邀请人",
    )
    _make_friends(
        client,
        caregiver_auth,
        owner_auth,
        recipient_username="owner_1",
    )
    shared_pet = _create_pet(
        client,
        caregiver_auth,
        name="奶糖",
        key="pending-shared-pet",
    )
    caregiver_invite = client.post(
        f"/api/v1/pets/{shared_pet['pet_id']}/caregiver-invitations",
        headers=caregiver_auth,
        json={"username": "owner_1", "role": "caregiver"},
    )
    assert caregiver_invite.status_code == 201, caregiver_invite.text

    visitor_auth = register_account(
        client,
        "pending_visitor",
        display_name="串门好友",
    )
    _make_friends(
        client,
        visitor_auth,
        owner_auth,
        recipient_username="owner_1",
    )
    visitor_pet = _create_pet(
        client,
        visitor_auth,
        name="豆包",
        key="pending-visitor-pet",
    )
    host_pet = _create_pet(
        client,
        owner_auth,
        name="团团",
        key="pending-host-pet",
    )
    privacy = client.patch(
        f"/api/v1/pets/{host_pet['pet_id']}/privacy",
        headers=owner_auth,
        json={"visibility": "friends", "allow_remote_care": False},
    )
    assert privacy.status_code == 200, privacy.text
    visit = client.post(
        "/api/v1/visits",
        headers=visitor_auth,
        json={
            "host_username": "owner_1",
            "visitor_pet_id": visitor_pet["pet_id"],
            "host_pet_id": host_pet["pet_id"],
            "duration_minutes": 45,
            "note": "一起玩一会儿",
        },
    )
    assert visit.status_code == 201, visit.text

    reminder = client.post(
        "/api/v1/reminders/occurrences",
        headers={**owner_auth, "Idempotency-Key": "pending-reminder-create"},
        json={
            "source": "test",
            "source_reminder_id": "pending-reminder-1",
            "title": "给团团准备晚餐",
            "content": "晚餐已经到时间。",
            "scheduled_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
            "timezone": "Asia/Shanghai",
            "priority": "high",
            "category": "pet-care",
            "version": 1,
        },
    )
    assert reminder.status_code == 201, reminder.text

    return {
        "friend_request": friend_request.json()["request_id"],
        "caregiver_invitation": caregiver_invite.json()["invitation_id"],
        "visit_request": visit.json()["visit_id"],
        "reminder_due": reminder.json()["occurrence_id"],
    }


def test_pending_items_unify_four_customer_workflows(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    ids = _seed_pending_items(client, account_auth)

    response = client.get("/api/v1/pending-items", headers=account_auth)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 4
    assert payload["urgent_count"] == 1
    assert [item["kind"] for item in payload["items"]][0] == "reminder_due"
    by_kind = {item["kind"]: item for item in payload["items"]}
    assert set(by_kind) == set(ids)
    assert by_kind["friend_request"]["actions"] == ["accept", "reject"]
    assert by_kind["caregiver_invitation"]["pet_name"] == "奶糖"
    assert by_kind["visit_request"]["pet_name"] == "团团"
    assert by_kind["reminder_due"]["actions"] == ["complete", "snooze", "dismiss"]


def test_pending_items_support_direct_customer_actions(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    ids = _seed_pending_items(client, account_auth)
    actions = (
        ("friend_request", ids["friend_request"], "accept", {}),
        ("caregiver_invitation", ids["caregiver_invitation"], "reject", {}),
        ("visit_request", ids["visit_request"], "reject", {}),
        ("reminder_due", ids["reminder_due"], "snooze", {"snooze_minutes": 10}),
    )
    for index, (kind, item_id, action, body) in enumerate(actions):
        response = client.post(
            f"/api/v1/pending-items/{kind}/{item_id}/{action}",
            headers={**account_auth, "Idempotency-Key": f"pending-action-{index}"},
            json=body,
        )
        assert response.status_code == 200, response.text
        assert response.json()["action"] == action

    remaining = client.get("/api/v1/pending-items", headers=account_auth)
    assert remaining.status_code == 200
    assert remaining.json()["count"] == 0


def test_device_can_read_and_process_the_same_pending_queue(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    ids = _seed_pending_items(client, account_auth)
    _device, device_auth, _secret = bind_device(
        client,
        account_auth,
        public_id="pending-items-device-0001",
    )

    queue = client.get("/api/v1/pending-items", headers=device_auth)
    assert queue.status_code == 200, queue.text
    assert queue.json()["count"] == 4

    completed = client.post(
        f"/api/v1/pending-items/reminder_due/{ids['reminder_due']}/complete",
        headers={**device_auth, "Idempotency-Key": "pending-device-complete"},
        json={},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["message"] == "提醒已完成。"
