from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog

from onepic_desktop_pet.party_client import PartyClient
from onepic_desktop_pet.party_dialog import DESKTOP_PARTY_WINDOW_LIMIT, PartyDialog


class FakeSession(QObject):
    state_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.connected = True


class FakeTransport(QObject):
    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[str, str, str, object]] = []

    def request(self, operation, method, path, *, body=None, query=None) -> None:
        self.requests.append((operation, method, path, body))


def _party_payload(*, status: str = "active") -> dict[str, object]:
    return {
        "party_id": "party-1",
        "title": "桌面宠物小聚会",
        "note": "轻量场景",
        "status": status,
        "host_account_id": "account-host",
        "host_pet_id": "pet-host",
        "max_members": 4,
        "duration_minutes": 60,
        "completion_reason": "",
        "created_at": "2026-07-28T12:00:00+00:00",
        "started_at": "2026-07-28T12:10:00+00:00" if status == "active" else None,
        "scheduled_end_at": "2026-07-28T13:10:00+00:00" if status == "active" else None,
        "ended_at": None,
        "member_count": 3,
        "accepted_count": 3,
        "joined_count": 3 if status == "active" else 0,
        "desktop_window_limit": 2,
        "desktop_render_mode": "single_scene",
        "can_invite": False,
        "can_start": False,
        "can_cancel": False,
        "can_end": True,
        "can_interact": True,
        "members": [
            {
                "member_id": "member-host",
                "account": {
                    "account_id": "account-host",
                    "username": "host",
                    "display_name": "发起人",
                },
                "pet": {"pet_id": "pet-host", "name": "团子"},
                "role": "host",
                "status": "joined",
                "is_current_account": True,
                "can_accept": False,
                "can_decline": False,
                "can_leave": False,
            },
            {
                "member_id": "member-one",
                "account": {
                    "account_id": "account-one",
                    "username": "one",
                    "display_name": "好友一",
                },
                "pet": {"pet_id": "pet-one", "name": "小白"},
                "role": "member",
                "status": "joined",
                "is_current_account": False,
                "can_accept": False,
                "can_decline": False,
                "can_leave": False,
            },
            {
                "member_id": "member-two",
                "account": {
                    "account_id": "account-two",
                    "username": "two",
                    "display_name": "好友二",
                },
                "pet": {"pet_id": "pet-two", "name": "豆包"},
                "role": "member",
                "status": "joined",
                "is_current_account": False,
                "can_accept": False,
                "can_decline": False,
                "can_leave": False,
            },
        ],
        "timeline": [
            {
                "event_id": "event-1",
                "kind": "started",
                "title": "聚会正式开始",
                "detail": "全部成员进入同一个聚会场景，桌面常驻窗口仍最多显示两只宠物。",
                "occurred_at": "2026-07-28T12:10:00+00:00",
                "actor_display_name": "发起人",
            }
        ],
    }


def test_party_client_uses_one_request_facade_without_sync_runtime() -> None:
    session = FakeSession()
    transport = FakeTransport()
    client = PartyClient(session, object(), transport=transport)
    snapshots: list[object] = []
    details: list[tuple[str, object]] = []
    mutations: list[tuple[str, object]] = []
    client.snapshot_received.connect(snapshots.append)
    client.detail_received.connect(lambda party_id, payload: details.append((party_id, payload)))
    client.mutation_succeeded.connect(lambda operation, payload: mutations.append((operation, payload)))

    assert client.refresh() is True
    assert transport.requests[-1] == ("party_list", "GET", "/api/v1/parties", None)
    transport.operation_succeeded.emit("party_list", {"active": [_party_payload()]})
    assert len(snapshots) == 1

    assert client.load_detail("party-1") is True
    assert transport.requests[-1][2] == "/api/v1/parties/party-1"
    transport.operation_succeeded.emit("party_detail:party-1", _party_payload())
    assert details == [("party-1", _party_payload())]

    assert client.create_party("pet-host", title="桌面聚会", duration_minutes=60, max_members=4)
    assert transport.requests[-1][2] == "/api/v1/parties"
    assert transport.requests[-1][3]["host_pet_id"] == "pet-host"

    assert client.interact("party-1", "play_together", "desktop-party-play-0001")
    operation, method, path, body = transport.requests[-1]
    assert operation == "party_interact:party-1:play_together"
    assert method == "POST"
    assert path.endswith("/interactions/play_together")
    assert body == {"idempotency_key": "desktop-party-play-0001"}
    transport.operation_succeeded.emit(operation, {"party_id": "party-1"})
    assert mutations[-1][0] == operation

    assert not hasattr(client, "sync_timer")
    assert not hasattr(client, "local_store")
    assert not hasattr(client, "message_cache")


def test_party_dialog_keeps_all_members_in_one_management_window() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = PartyDialog()
    created: list[tuple[str, str, int, int]] = []
    details: list[str] = []
    interactions: list[tuple[str, str, str]] = []
    dialog.create_requested.connect(
        lambda pet_id, title, duration, count: created.append(
            (pet_id, title, duration, count)
        )
    )
    dialog.detail_requested.connect(details.append)
    dialog.interaction_requested.connect(
        lambda party_id, action, key: interactions.append((party_id, action, key))
    )
    dialog.set_current_pet("pet-host", "团子", available=True)
    dialog.show()
    app.processEvents()

    assert DESKTOP_PARTY_WINDOW_LIMIT == 2
    assert dialog.findChildren(QDialog) == []
    dialog.create_button.click()
    assert created == [("pet-host", "宠物小聚会", 60, 4)]

    party = _party_payload()
    dialog.set_snapshot(
        {"invitations": [], "open": [], "active": [party], "history": []}
    )
    app.processEvents()
    assert dialog.party_list.count() == 1
    assert details == ["party-1"]

    dialog.set_detail(party)
    assert dialog.member_table.rowCount() == 3
    assert dialog.party_meta_label.text().endswith("桌面常驻上限 2 只")
    assert "最多显示两只" in dialog.timeline_list.item(0).text()
    assert dialog.end_button.isEnabled() is True
    assert all(button.isEnabled() for button in dialog.interaction_buttons.values())

    dialog.interaction_buttons["play_together"].click()
    assert interactions
    assert interactions[-1][0:2] == ("party-1", "play_together")
    assert interactions[-1][2].startswith("desktop-party-play_together-")

    dialog.close()
    app.processEvents()
