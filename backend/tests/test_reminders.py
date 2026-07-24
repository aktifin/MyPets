from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from mypets_backend.reminder_provider import ProviderOccurrence, ReminderProvider


def _register_account(
    client: TestClient,
    username: str,
    *,
    display_name: str | None = None,
) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": display_name or username,
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _bind_device(
    client: TestClient,
    account_auth: dict[str, str],
    *,
    public_id: str = "windows-reminder-device-0001",
) -> tuple[dict, dict[str, str]]:
    bound = client.post(
        "/api/v1/devices/bind",
        headers=account_auth,
        json={"public_id": public_id, "name": "提醒测试电脑", "platform": "windows"},
    )
    assert bound.status_code == 201, bound.text
    binding = bound.json()
    exchanged = client.post(
        "/api/v1/auth/device-token",
        json={
            "device_id": binding["device"]["id"],
            "device_secret": binding["device_secret"],
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    return binding["device"], {
        "Authorization": f"Bearer {exchanged.json()['access_token']}"
    }


def _payload(*, version: int = 1, minutes: int = 30) -> dict:
    return {
        "source": "myreminder",
        "source_reminder_id": "source-reminder-001",
        "title": "给猫咪准备晚饭",
        "content": "检查猫粮和饮水",
        "scheduled_at": (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(),
        "timezone": "Asia/Tokyo",
        "priority": "high",
        "category": "pet_care",
        "version": version,
    }


def _create(
    client: TestClient,
    auth: dict[str, str],
    *,
    key: str = "reminder-create-0001",
    payload: dict | None = None,
):
    return client.post(
        "/api/v1/reminders/occurrences",
        headers={**auth, "Idempotency-Key": key},
        json=payload or _payload(),
    )


def test_provider_contract_requires_timezone() -> None:
    occurrence = ProviderOccurrence(
        source_reminder_id="provider-1",
        title="喝水",
        content="",
        scheduled_at=datetime.now(UTC),
        timezone="Asia/Tokyo",
    )
    assert occurrence.version == 1
    assert isinstance(object(), ReminderProvider) is False


def test_reminder_delivery_snooze_complete_and_sync_events(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    _device, device_auth = _bind_device(client, account_auth)
    created = _create(client, account_auth)
    assert created.status_code == 201, created.text
    occurrence = created.json()
    occurrence_id = occurrence["occurrence_id"]
    assert occurrence["state"] == "pending"
    assert occurrence["version"] == 1

    replay = _create(client, account_auth)
    assert replay.status_code == 201
    assert replay.json()["occurrence_id"] == occurrence_id

    snapshot = client.get("/api/v1/reminders/snapshot", headers=device_auth)
    assert snapshot.status_code == 200
    assert snapshot.json()["count"] == 1
    assert snapshot.json()["items"][0]["occurrence_id"] == occurrence_id

    delivered = client.post(
        f"/api/v1/reminders/occurrences/{occurrence_id}/delivered",
        headers={**device_auth, "Idempotency-Key": "reminder-deliver-0001"},
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["occurrence"]["state"] == "delivered"
    assert delivered.json()["occurrence"]["last_delivered_at"] is not None

    snoozed = client.post(
        f"/api/v1/reminders/occurrences/{occurrence_id}/snooze",
        headers={**device_auth, "Idempotency-Key": "reminder-snooze-0001"},
        json={"minutes": 10},
    )
    assert snoozed.status_code == 200, snoozed.text
    assert snoozed.json()["occurrence"]["state"] == "pending"
    assert snoozed.json()["occurrence"]["version"] == 2
    assert snoozed.json()["occurrence"]["snooze_count"] == 1

    completed = client.post(
        f"/api/v1/reminders/occurrences/{occurrence_id}/complete",
        headers={**device_auth, "Idempotency-Key": "reminder-complete-0001"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["occurrence"]["state"] == "completed"
    assert completed.json()["occurrence"]["completed_at"] is not None

    completed_replay = client.post(
        f"/api/v1/reminders/occurrences/{occurrence_id}/complete",
        headers={**device_auth, "Idempotency-Key": "reminder-complete-0001"},
    )
    assert completed_replay.status_code == 200
    assert completed_replay.json()["occurrence"]["state"] == "completed"

    events = client.get(
        "/api/v1/sync/events?after_sequence=0&limit=200",
        headers=device_auth,
    )
    assert events.status_code == 200, events.text
    event_types = {item["event_type"] for item in events.json()["events"]}
    assert {
        "reminder_occurrence_upserted",
        "reminder_delivered",
        "reminder_snoozed",
        "reminder_completed",
    }.issubset(event_types)


def test_reminder_import_rejects_stale_or_terminal_revival(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    _device, device_auth = _bind_device(client, account_auth)
    created = _create(client, account_auth)
    occurrence_id = created.json()["occurrence_id"]

    inconsistent = _payload(version=1)
    inconsistent["title"] = "同版本被篡改"
    conflict = _create(
        client,
        account_auth,
        key="reminder-create-conflict",
        payload=inconsistent,
    )
    assert conflict.status_code == 409

    stale = _create(
        client,
        account_auth,
        key="reminder-create-stale",
        payload=_payload(version=0),
    )
    assert stale.status_code == 422

    completed = client.post(
        f"/api/v1/reminders/occurrences/{occurrence_id}/complete",
        headers={**device_auth, "Idempotency-Key": "reminder-terminal-complete"},
    )
    assert completed.status_code == 200

    revival = _create(
        client,
        account_auth,
        key="reminder-terminal-revival",
        payload=_payload(version=2),
    )
    assert revival.status_code == 409


def test_reminders_are_account_scoped_and_delivery_requires_device_token(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    created = _create(client, account_auth)
    occurrence_id = created.json()["occurrence_id"]

    account_delivery = client.post(
        f"/api/v1/reminders/occurrences/{occurrence_id}/delivered",
        headers={**account_auth, "Idempotency-Key": "reminder-wrong-token"},
    )
    assert account_delivery.status_code == 403

    other_auth = _register_account(client, "other_reminder_owner")
    other_device, other_device_auth = _bind_device(
        client,
        other_auth,
        public_id="other-reminder-device",
    )
    assert other_device["id"]
    other_list = client.get("/api/v1/reminders/occurrences", headers=other_device_auth)
    assert other_list.status_code == 200
    assert other_list.json() == []

    cross_account = client.post(
        f"/api/v1/reminders/occurrences/{occurrence_id}/complete",
        headers={**other_device_auth, "Idempotency-Key": "reminder-cross-account"},
    )
    assert cross_account.status_code == 404
