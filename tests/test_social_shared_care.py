from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.social_client import SocialController
from onepic_desktop_pet.social_dialog import SocialDialog


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


def test_social_controller_refreshes_and_requests_pet_sync_after_relationship_change() -> None:
    session = FakeSession(True)
    transport = FakeTransport()
    controller = SocialController(session, object(), transport=transport)
    snapshots: list[dict] = []
    statuses: list[str] = []
    failures: list[str] = []
    pet_syncs: list[bool] = []
    controller.snapshot_changed.connect(snapshots.append)
    controller.status_message.connect(statuses.append)
    controller.operation_failed.connect(failures.append)
    controller.pets_sync_requested.connect(lambda: pet_syncs.append(True))

    assert controller.refresh("pet-1") is True
    assert {item[0] for item in transport.requests} == {
        "friends",
        "friend_requests",
        "blocks",
        "caregiver_invitations",
        "pet_privacy",
        "pet_caregivers",
    }
    payloads = {
        "friends": [],
        "friend_requests": {"incoming": [], "outgoing": []},
        "blocks": [],
        "caregiver_invitations": {"incoming": [], "outgoing": []},
        "pet_privacy": {
            "pet_id": "pet-1",
            "visibility": "friends",
            "allow_remote_care": True,
        },
        "pet_caregivers": [],
    }
    for operation, payload in payloads.items():
        transport.operation_succeeded.emit(operation, payload)
    assert snapshots[-1]["pet_privacy"]["visibility"] == "friends"
    assert statuses[-1] == "好友与共同照料数据已刷新"

    controller.respond_caregiver_invitation("invite-1", "accept")
    operation, method, path, _body = transport.requests[-1]
    assert operation == "mutation:caregiver_invitation_accept"
    assert method == "POST"
    assert path.endswith("/invite-1/accept")
    transport.operation_succeeded.emit(operation, {"status": "accepted"})
    assert pet_syncs == [True]

    session.connected = False
    controller.send_friend_request("somebody")
    assert failures[-1] == "云端未连接，操作未提交"


def test_social_dialog_populates_tables_and_emits_actions() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = SocialDialog()
    dialog.set_context(
        account_id="account-1",
        display_name="主人",
        active_pet_id="pet-1",
        active_pet_name="小云",
        can_manage_pet=True,
    )
    snapshot = {
        "friend_requests": {
            "incoming": [
                {
                    "request_id": "request-1",
                    "sender": {
                        "account_id": "account-2",
                        "username": "friend_2",
                        "display_name": "好友二",
                    },
                    "created_at": "2026-07-25T10:00:00+09:00",
                }
            ],
            "outgoing": [],
        },
        "friends": [
            {
                "friendship_id": "friendship-1",
                "friend": {
                    "account_id": "account-2",
                    "username": "friend_2",
                    "display_name": "好友二",
                },
                "created_at": "2026-07-25T10:01:00+09:00",
            }
        ],
        "blocks": [
            {
                "account": {
                    "account_id": "account-3",
                    "username": "blocked_3",
                    "display_name": "已屏蔽",
                },
                "created_at": "2026-07-25T10:02:00+09:00",
            }
        ],
        "caregiver_invitations": {
            "incoming": [
                {
                    "invitation_id": "invite-1",
                    "pet": {"name": "小雪"},
                    "invited_by": {"display_name": "好友二"},
                    "role": "caregiver",
                    "created_at": "2026-07-25T10:03:00+09:00",
                }
            ],
            "outgoing": [],
        },
        "pet_privacy": {
            "pet_id": "pet-1",
            "visibility": "friends",
            "allow_remote_care": True,
        },
        "pet_caregivers": [
            {
                "account": {
                    "account_id": "account-2",
                    "username": "friend_2",
                    "display_name": "好友二",
                },
                "relation": {
                    "role": "caregiver",
                    "care_contribution": 7,
                },
            }
        ],
    }
    dialog.apply_snapshot(snapshot)
    assert dialog.friend_requests_table.rowCount() == 1
    assert dialog.friends_table.rowCount() == 1
    assert dialog.blocks_table.rowCount() == 1
    assert dialog.caregiver_invites_table.rowCount() == 1
    assert dialog.caregivers_table.rowCount() == 1
    assert dialog.visibility_combo.currentData() == "friends"
    assert dialog.remote_care_checkbox.isChecked() is True

    friend_actions: list[tuple[str, str]] = []
    privacy_actions: list[tuple[str, bool]] = []
    invite_actions: list[tuple[str, str]] = []
    dialog.friend_request_action_requested.connect(
        lambda request_id, action: friend_actions.append((request_id, action))
    )
    dialog.privacy_save_requested.connect(
        lambda visibility, allowed: privacy_actions.append((visibility, allowed))
    )
    dialog.caregiver_invitation_action_requested.connect(
        lambda invite_id, action: invite_actions.append((invite_id, action))
    )

    dialog.friend_requests_table.selectRow(0)
    dialog._friend_request_action("accept")
    dialog._save_privacy()
    dialog.caregiver_invites_table.selectRow(0)
    dialog._caregiver_invite_action("accept")
    assert friend_actions == [("request-1", "accept")]
    assert privacy_actions == [("friends", True)]
    assert invite_actions == [("invite-1", "accept")]

    dialog.set_context(
        account_id="account-1",
        display_name="主人",
        active_pet_id="pet-2",
        active_pet_name="朋友的宠物",
        can_manage_pet=False,
    )
    assert dialog.visibility_combo.isEnabled() is False
    assert dialog.caregiver_username.isEnabled() is False
    dialog.close()
    assert app is not None
