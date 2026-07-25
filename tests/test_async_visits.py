from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.visit_client import VisitController
from onepic_desktop_pet.visit_dialog import VisitDialog


class FakeSession(QObject):
    state_changed = Signal(str)

    def __init__(self, connected: bool = True) -> None:
        super().__init__()
        self.connected = connected


class FakeTransport(QObject):
    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[str, str, str, object]] = []

    def request(self, operation, method, path, *, body=None, query=None) -> None:
        self.requests.append((operation, method, path, body))


def test_visit_controller_refreshes_loads_friend_pets_and_syncs_after_accept() -> None:
    session = FakeSession(True)
    transport = FakeTransport()
    controller = VisitController(session, object(), transport=transport)
    snapshots: list[dict] = []
    statuses: list[str] = []
    failures: list[str] = []
    syncs: list[bool] = []
    controller.snapshot_changed.connect(snapshots.append)
    controller.status_message.connect(statuses.append)
    controller.operation_failed.connect(failures.append)
    controller.pets_sync_requested.connect(lambda: syncs.append(True))

    assert controller.refresh("visitor-pet") is True
    assert {item[0] for item in transport.requests} == {"friends", "visits"}
    transport.operation_succeeded.emit("friends", [])
    transport.operation_succeeded.emit(
        "visits",
        {"incoming_requests": [], "outgoing_requests": [], "active": [], "history": []},
    )
    assert snapshots[-1]["visits"]["active"] == []
    assert statuses[-1] == "串门数据已刷新"

    controller.load_friend_pets("friend-account")
    operation, method, path, body = transport.requests[-1]
    assert (operation, method, body) == ("friend_pets", "GET", None)
    assert path.endswith("/friends/friend-account/pets")
    transport.operation_succeeded.emit("friend_pets", [{"pet_id": "host-pet", "name": "小主"}])
    assert snapshots[-1]["friend_pets"][0]["pet_id"] == "host-pet"

    controller.request_visit("friend_user", "host-pet", 60, "一起玩")
    operation, method, path, body = transport.requests[-1]
    assert operation == "mutation:request_visit"
    assert method == "POST"
    assert path == "/api/v1/visits"
    assert body["visitor_pet_id"] == "visitor-pet"
    assert body["host_pet_id"] == "host-pet"

    controller.respond_visit("visit-1", "accept")
    operation = transport.requests[-1][0]
    assert operation == "mutation:visit_accept"
    transport.operation_succeeded.emit(operation, {"status": "active"})
    assert syncs == [True]

    session.connected = False
    controller.recall_visit("visit-1")
    assert failures[-1] == "云端未连接，串门操作未提交"


def test_visit_dialog_populates_requests_active_history_and_emits_actions() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = VisitDialog()
    dialog.set_context(
        account_id="account-1",
        display_name="主人",
        active_pet_id="visitor-pet",
        active_pet_name="小访客",
        can_request=True,
    )
    account_1 = {"account_id": "account-1", "username": "owner", "display_name": "主人"}
    account_2 = {"account_id": "account-2", "username": "friend_2", "display_name": "好友二"}
    visitor = {
        "pet_id": "visitor-pet",
        "name": "小访客",
        "presence": "visiting",
        "growth_stage": "child",
        "growth_level": 3,
        "mood": 80,
    }
    host_pet = {
        "pet_id": "host-pet",
        "name": "小主人",
        "presence": "home",
        "growth_stage": "child",
        "growth_level": 2,
        "mood": 90,
    }
    base_visit = {
        "visit_id": "visit-1",
        "requester": account_1,
        "host": account_2,
        "visitor_pet": visitor,
        "host_pet": host_pet,
        "status": "pending",
        "note": "一起玩",
        "duration_minutes": 60,
        "completion_reason": "",
        "created_at": "2026-07-25T10:00:00+09:00",
        "responded_at": None,
        "started_at": None,
        "scheduled_end_at": None,
        "completed_at": None,
        "can_accept": False,
        "can_reject": False,
        "can_cancel": True,
        "can_recall": False,
    }
    active = {
        **base_visit,
        "visit_id": "visit-active",
        "status": "active",
        "started_at": "2026-07-25T10:05:00+09:00",
        "scheduled_end_at": "2026-07-25T11:05:00+09:00",
        "can_cancel": False,
        "can_recall": True,
    }
    history = {
        **base_visit,
        "visit_id": "visit-history",
        "status": "completed",
        "completion_reason": "visit_auto_returned",
        "completed_at": "2026-07-25T11:05:00+09:00",
        "can_cancel": False,
    }
    dialog.apply_snapshot(
        {
            "friends": [
                {
                    "friendship_id": "friendship-1",
                    "friend": account_2,
                    "created_at": "2026-07-25T09:00:00+09:00",
                }
            ],
            "friend_pets": [host_pet],
            "visits": {
                "incoming_requests": [{**base_visit, "requester": account_2, "host": account_1}],
                "outgoing_requests": [base_visit],
                "active": [active],
                "history": [history],
            },
        }
    )
    assert dialog.friend_combo.count() == 1
    assert dialog.host_pet_combo.count() == 1
    assert dialog.incoming_table.rowCount() == 1
    assert dialog.outgoing_table.rowCount() == 1
    assert dialog.active_table.rowCount() == 1
    assert dialog.history_table.rowCount() == 1
    assert dialog.history_table.item(0, 4).text() == "到期自动返家"

    loaded: list[str] = []
    requested: list[tuple[str, str, int, str]] = []
    actions: list[tuple[str, str]] = []
    recalls: list[str] = []
    dialog.friend_pets_requested.connect(loaded.append)
    dialog.visit_request_requested.connect(
        lambda username, pet_id, minutes, note: requested.append(
            (username, pet_id, minutes, note)
        )
    )
    dialog.visit_action_requested.connect(
        lambda visit_id, action: actions.append((visit_id, action))
    )
    dialog.visit_recall_requested.connect(recalls.append)

    dialog._load_friend_pets()
    dialog.note_edit.setText("新的留言")
    dialog._send_visit()
    dialog.incoming_table.selectRow(0)
    dialog._request_action(dialog.incoming_table, "accept")
    dialog.active_table.selectRow(0)
    dialog._recall()
    assert loaded == ["account-2"]
    assert requested == [("friend_2", "host-pet", 30, "新的留言")]
    assert actions == [("visit-1", "accept")]
    assert recalls == ["visit-active"]

    dialog.set_context(
        account_id="account-1",
        display_name="主人",
        active_pet_id="shared-pet",
        active_pet_name="共享宠物",
        can_request=False,
    )
    assert dialog.send_button.isEnabled() is False
    dialog.close()
    assert app is not None
