from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from mypets_backend.reminder_provider import ProviderOccurrence


class MutableProvider:
    provider_id = "myreminder"

    def __init__(self, values: list[ProviderOccurrence]) -> None:
        self.values = values
        self.calls: list[tuple[str, datetime, datetime]] = []

    def pull_occurrences(
        self,
        *,
        account_external_id: str,
        window_start: datetime,
        window_end: datetime,
    ):
        self.calls.append((account_external_id, window_start, window_end))
        return list(self.values)


def _register(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "owner_1",
            "display_name": "主人",
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _bind_device(
    client: TestClient,
    account_auth: dict[str, str],
) -> dict[str, str]:
    bound = client.post(
        "/api/v1/devices/bind",
        headers=account_auth,
        json={
            "public_id": "reminder-provider-test-device",
            "name": "测试电脑",
            "platform": "windows",
        },
    )
    assert bound.status_code == 201, bound.text
    exchanged = client.post(
        "/api/v1/auth/device-token",
        json={
            "device_id": bound.json()["device"]["id"],
            "device_secret": bound.json()["device_secret"],
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    return {"Authorization": f"Bearer {exchanged.json()['access_token']}"}


def _occurrence(
    source_id: str,
    scheduled_at: datetime,
    *,
    title: str,
    version: int = 1,
) -> ProviderOccurrence:
    return ProviderOccurrence(
        source_reminder_id=source_id,
        title=title,
        content=f"{title}的正文",
        scheduled_at=scheduled_at,
        timezone="Asia/Tokyo",
        priority="normal",
        category="general",
        version=version,
    )


def test_sync_creates_updates_expires_and_preserves_terminal_occurrences(
    client: TestClient,
) -> None:
    account_auth = _register(client)
    device_auth = _bind_device(client, account_auth)
    now = datetime.now(UTC)
    first_time = now + timedelta(hours=2)
    provider = MutableProvider(
        [
            _occurrence("rule-1:2026-07-25", first_time, title="喝水"),
            _occurrence("rule-2:2026-07-25", first_time + timedelta(hours=1), title="休息"),
        ]
    )
    client.app.state.myreminder_provider_factory = lambda _settings: provider

    status = client.get(
        "/api/v1/reminder-providers/myreminder/status",
        headers=device_auth,
    )
    assert status.status_code == 200
    assert status.json()["configured"] is False

    created = client.post(
        "/api/v1/reminder-providers/myreminder/sync",
        headers=device_auth,
    )
    assert created.status_code == 200, created.text
    assert created.json()["external_username"] == "owner_1"
    assert created.json()["pulled"] == 2
    assert created.json()["created"] == 2
    assert provider.calls[0][0] == "owner_1"

    snapshot = client.get("/api/v1/reminders/snapshot", headers=device_auth)
    assert snapshot.status_code == 200
    items = snapshot.json()["items"]
    assert {item["source_reminder_id"] for item in items} == {
        "rule-1:2026-07-25",
        "rule-2:2026-07-25",
    }
    first_id = next(
        item["occurrence_id"]
        for item in items
        if item["source_reminder_id"] == "rule-1:2026-07-25"
    )

    provider.values = [
        _occurrence(
            "rule-1:2026-07-25",
            first_time + timedelta(minutes=15),
            title="定时喝水",
            version=2,
        )
    ]
    changed = client.post(
        "/api/v1/reminder-providers/myreminder/sync",
        headers=device_auth,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["updated"] == 1
    assert changed.json()["expired"] == 1

    after_change = client.get("/api/v1/reminders/snapshot", headers=device_auth).json()["items"]
    first = next(item for item in after_change if item["occurrence_id"] == first_id)
    second = next(item for item in after_change if item["source_reminder_id"].startswith("rule-2:"))
    assert first["title"] == "定时喝水"
    assert first["version"] >= 2
    assert second["state"] == "expired"

    completed = client.post(
        f"/api/v1/reminders/occurrences/{first_id}/complete",
        headers={**device_auth, "Idempotency-Key": "provider-terminal-complete"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["occurrence"]["state"] == "completed"

    provider.values = [
        _occurrence(
            "rule-1:2026-07-25",
            first_time + timedelta(minutes=30),
            title="再次修改",
            version=3,
        )
    ]
    preserved = client.post(
        "/api/v1/reminder-providers/myreminder/sync",
        headers=device_auth,
    )
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["terminal_preserved"] == 1
    final_item = next(
        item
        for item in client.get("/api/v1/reminders/snapshot", headers=device_auth).json()["items"]
        if item["occurrence_id"] == first_id
    )
    assert final_item["state"] == "completed"
    assert final_item["title"] == "定时喝水"

    events = client.get(
        "/api/v1/sync/events?after_sequence=0&limit=200",
        headers=device_auth,
    )
    assert events.status_code == 200
    event_types = {item["event_type"] for item in events.json()["events"]}
    assert "reminder_occurrence_upserted" in event_types
    assert "reminder_expired" in event_types
