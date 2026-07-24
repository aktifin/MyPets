from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mypets_backend.config import Settings
from mypets_backend.myreminder_provider import (
    MyReminderHttpProvider,
    normalize_myreminder_base_url,
)


class FakeTransport:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def fetch_rules(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


def _payload(username: str = "owner_1") -> dict:
    return {
        "success": True,
        "data": {
            "provider": "myreminder",
            "user": {"username": username, "display_name": "主人"},
            "rules": [
                {
                    "id": "10",
                    "title": "喝水",
                    "content": "补充水分",
                    "time": "08:30",
                    "timezone": "Asia/Tokyo",
                    "weekdays": [1, 3, 5],
                    "enabled": True,
                    "priority": "normal",
                    "category": "health",
                    "version": 7,
                },
                {
                    "id": "11",
                    "title": "已停用",
                    "content": "不会展开",
                    "time": "09:00",
                    "timezone": "Asia/Tokyo",
                    "weekdays": [1, 2, 3, 4, 5, 6, 7],
                    "enabled": False,
                    "priority": "normal",
                    "category": "general",
                    "version": 1,
                },
            ],
        },
    }


def test_provider_expands_weekday_rules_in_source_timezone() -> None:
    transport = FakeTransport(_payload())
    provider = MyReminderHttpProvider(
        base_url="http://127.0.0.1:3457/",
        integration_secret="test-secret-with-more-than-24-characters",
        transport=transport,
    )
    values = list(
        provider.pull_occurrences(
            account_external_id="OWNER_1",
            window_start=datetime(2026, 7, 19, 15, 0, tzinfo=UTC),
            window_end=datetime(2026, 7, 26, 15, 0, tzinfo=UTC),
        )
    )

    assert [item.source_reminder_id for item in values] == [
        "10:2026-07-20",
        "10:2026-07-22",
        "10:2026-07-24",
    ]
    assert [item.scheduled_at.isoformat() for item in values] == [
        "2026-07-19T23:30:00+00:00",
        "2026-07-21T23:30:00+00:00",
        "2026-07-23T23:30:00+00:00",
    ]
    assert all(item.version == 7 for item in values)
    assert transport.calls[0]["username"] == "owner_1"


def test_provider_rejects_cross_account_payload_and_invalid_service_url() -> None:
    provider = MyReminderHttpProvider(
        base_url="http://localhost:3457",
        integration_secret="test-secret-with-more-than-24-characters",
        transport=FakeTransport(_payload("other_user")),
    )
    with pytest.raises(RuntimeError, match="其他账户"):
        list(
            provider.pull_occurrences(
                account_external_id="owner_1",
                window_start=datetime(2026, 7, 20, tzinfo=UTC),
                window_end=datetime(2026, 7, 21, tzinfo=UTC),
            )
        )

    with pytest.raises(ValueError):
        normalize_myreminder_base_url("file:///tmp/reminders")
    with pytest.raises(ValueError):
        normalize_myreminder_base_url("http://user:pass@example.com")


def test_settings_require_service_url_and_secret_together() -> None:
    with pytest.raises(ValueError, match="同时配置"):
        Settings(
            jwt_secret="test-secret-with-more-than-24-characters",
            myreminder_base_url="http://127.0.0.1:3457",
        ).validate()
    settings = Settings(
        jwt_secret="test-secret-with-more-than-24-characters",
        myreminder_base_url="http://127.0.0.1:3457/",
        myreminder_integration_secret="integration-secret-with-more-than-24-chars",
    )
    settings.validate()
    assert settings.myreminder_configured is True
    assert settings.myreminder_base_url == "http://127.0.0.1:3457"
