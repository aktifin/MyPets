"""SQLite 本地状态仓库和多宠物注册表测试。

测试只使用 pytest 临时目录，不访问真实用户数据、网络或 GUI。
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from onepic_desktop_pet.domain import (
    AccountPetRelation,
    CloudEvent,
    FoldedNotification,
    NotificationKind,
    PetIdentity,
    PetProfile,
    PetRole,
    ReminderOccurrence,
    ReminderOccurrenceState,
)
from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.pet_registry import PetRegistry


def _profile(pet_id: str, name: str) -> PetProfile:
    return PetProfile(
        identity=PetIdentity(
            pet_id=pet_id,
            name=name,
            template_id="official.test",
            template_version="1.0.0",
            identity_version="1.0.0",
            primary_owner_account_id="account-1",
        ),
        updated_at=datetime(2026, 7, 24, tzinfo=UTC),
    )


def test_registry_persists_multiple_pets_and_active_selection(
    tmp_path: Path,
) -> None:
    store = LocalStateStore(tmp_path / "state.db")
    registry = PetRegistry(store)
    registry.register_pet(
        _profile("pet-1", "小白"),
        AccountPetRelation("account-1", "pet-1", PetRole.OWNER),
        make_active=True,
    )
    registry.register_pet(_profile("pet-2", "可乐"))

    assert {pet.identity.pet_id for pet in registry.list_pets()} == {
        "pet-1",
        "pet-2",
    }
    active = registry.active_pet()
    assert active is not None
    assert active.identity.pet_id == "pet-1"
    assert registry.switch_active_pet("pet-2").identity.name == "可乐"
    store.close()

    reopened = LocalStateStore(tmp_path / "state.db")
    assert reopened.get_active_pet_id() == "pet-2"
    first = reopened.get_pet("pet-1")
    assert first is not None
    assert first.updated_at == datetime(2026, 7, 24, tzinfo=UTC)
    reopened.close()


def test_bootstrap_creates_one_compatible_local_pet(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.db")
    registry = PetRegistry(store)

    first = registry.bootstrap_local_pet()
    second = registry.bootstrap_local_pet()

    assert first.identity.pet_id == second.identity.pet_id
    assert len(registry.list_pets()) == 1
    assert store.list_relations(first.identity.pet_id)[0].role is PetRole.OWNER
    store.close()


def test_folded_notifications_keep_message_and_reminder_counts_separate(
    tmp_path: Path,
) -> None:
    store = LocalStateStore(tmp_path / "state.db")
    now = datetime(2026, 7, 24, 8, tzinfo=UTC)
    for identifier, kind in (
        ("n1", NotificationKind.MESSAGE),
        ("n2", NotificationKind.REMINDER),
    ):
        store.put_notification(
            FoldedNotification(
                identifier,
                "account-1",
                kind,
                "标题",
                "正文",
                now,
            )
        )

    assert store.unread_counts("account-1") == {
        NotificationKind.MESSAGE: 1,
        NotificationKind.REMINDER: 1,
    }
    store.mark_notification_read("n1")
    store.archive_notification("n2")
    assert store.list_notifications("account-1", unread_only=True) == []
    store.close()


def test_store_entry_points_reject_naive_datetime(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.db")

    notification = FoldedNotification(
        "n1",
        "account-1",
        NotificationKind.SYSTEM,
        "标题",
        "正文",
        datetime(2026, 7, 24),
    )
    try:
        store.put_notification(notification)
    except ValueError as exc:
        assert "时区" in str(exc)
    else:
        raise AssertionError("无时区通知不应写入")

    try:
        store.list_due_reminders("account-1", datetime(2026, 7, 24))
    except ValueError as exc:
        assert "时区" in str(exc)
    else:
        raise AssertionError("无时区查询时间不应被接受")
    store.close()


def test_reminder_versions_and_due_query(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.db")
    now = datetime(2026, 7, 24, 8, tzinfo=UTC)
    original = ReminderOccurrence(
        "r1",
        "myreminder",
        "source-1",
        "account-1",
        "交报告",
        "交报告",
        now,
        "UTC",
        version=2,
    )
    stale = ReminderOccurrence(
        "r1",
        "myreminder",
        "source-1",
        "account-1",
        "旧标题",
        "旧内容",
        now,
        "UTC",
        version=1,
    )
    future = ReminderOccurrence(
        "r2",
        "myreminder",
        "source-2",
        "account-1",
        "喝水",
        "喝水",
        now + timedelta(hours=1),
        "UTC",
    )
    store.put_reminder(original)
    store.put_reminder(stale)
    store.put_reminder(future)

    due = store.list_due_reminders("account-1", now)
    assert [item.occurrence_id for item in due] == ["r1"]
    assert due[0].title == "交报告"
    store.set_reminder_state("r1", ReminderOccurrenceState.COMPLETED)
    assert store.list_due_reminders("account-1", now) == []
    store.close()


def test_outbox_is_idempotent_and_cursor_is_monotonic(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.db")
    event = CloudEvent(
        "e1",
        "pet_stats_changed",
        7,
        "idem-1",
        datetime(2026, 7, 24, tzinfo=UTC),
        {"pet_id": "pet-1"},
        "account-1",
    )

    assert store.enqueue_event(event)
    assert not store.enqueue_event(event)
    assert store.pending_events() == [event]

    store.set_cursor("account:account-1", 10)
    store.set_cursor("account:account-1", 8)
    assert store.get_cursor("account:account-1") == 10

    store.acknowledge_event("e1")
    assert store.pending_events() == []
    store.close()
