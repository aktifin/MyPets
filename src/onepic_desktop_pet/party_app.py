"""Final desktop composition layer for the bounded multi-pet party experience."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction

from .message_efficiency_app import MessageEfficiencyApplication
from .party_client import PartyClient
from .party_dialog import PartyDialog
from .party_pending_dialog import PartyPendingItemsDialog


class PartyApplication(MessageEfficiencyApplication):
    """Add one party panel without creating any additional desktop pet runtime."""

    def __init__(self, *args, **kwargs) -> None:
        self._party_dialog: PartyDialog | None = None
        super().__init__(*args, **kwargs)
        self.party_client = PartyClient(
            self.cloud_session,
            self.cloud_api,
            parent=self.qt_app,
        )
        self.party_client.snapshot_received.connect(self._party_snapshot_received)
        self.party_client.detail_received.connect(self._party_detail_received)
        self.party_client.mutation_succeeded.connect(self._party_mutation_succeeded)
        self.party_client.request_failed.connect(self._party_request_failed)
        self.cloud_session.state_changed.connect(self._party_cloud_state_changed)

        menu = self.system_tray_menu.menu
        self.party_action = QAction("宠物聚会…", menu)
        self.party_action.triggered.connect(self.open_party_dialog)
        separator = next((action for action in menu.actions() if action.isSeparator()), None)
        if separator is not None:
            menu.insertAction(separator, self.party_action)
        else:
            menu.addAction(self.party_action)
        self._refresh_party_action()

    def open_pending_items_dialog(self) -> None:
        if self._pending_items_dialog is None:
            dialog = PartyPendingItemsDialog()
            dialog.refresh_requested.connect(self.refresh_pending_items)
            dialog.action_requested.connect(self._act_on_pending_item)
            dialog.detail_requested.connect(self._open_pending_detail)
            self._pending_items_dialog = dialog
        self._sync_pending_items_dialog()
        self._pending_items_dialog.show()
        self._pending_items_dialog.raise_()
        self._pending_items_dialog.activateWindow()
        self.refresh_pending_items()

    def _open_pending_detail(self, payload: object) -> None:
        if isinstance(payload, dict) and str(payload.get("kind") or "") == "party_invitation":
            party_id = str(payload.get("item_id") or "")
            if party_id:
                self.open_party_dialog()
                QTimer.singleShot(
                    50,
                    lambda value=party_id: self.party_client.load_detail(value),
                )
            return
        super()._open_pending_detail(payload)

    def open_party_dialog(self) -> None:
        if self._party_dialog is None:
            dialog = PartyDialog()
            dialog.refresh_requested.connect(self.party_client.refresh)
            dialog.detail_requested.connect(self.party_client.load_detail)
            dialog.create_requested.connect(self._create_party)
            dialog.invite_requested.connect(self.party_client.invite)
            dialog.accept_requested.connect(self.party_client.accept)
            dialog.action_requested.connect(self._party_action_requested)
            dialog.interaction_requested.connect(self.party_client.interact)
            self._party_dialog = dialog
        self._sync_party_context()
        self._party_dialog.show()
        self._party_dialog.raise_()
        self._party_dialog.activateWindow()
        self._party_dialog.set_busy(True)
        self.party_client.refresh()

    def _sync_party_context(self) -> None:
        if self._party_dialog is None:
            return
        pet_id = self._visit_active_pet_id()
        presence_value = str(
            getattr(self.active_pet.presence, "value", self.active_pet.presence)
        ).lower()
        self._party_dialog.set_current_pet(
            pet_id,
            self.active_pet.identity.name if pet_id else "",
            available=bool(pet_id and presence_value in {"home", "resting"}),
        )

    def _create_party(
        self,
        pet_id: str,
        title: str,
        duration_minutes: int,
        max_members: int,
    ) -> None:
        self.party_client.create_party(
            pet_id,
            title=title,
            duration_minutes=duration_minutes,
            max_members=max_members,
        )

    def _party_action_requested(self, party_id: str, action: str) -> None:
        operations = {
            "decline": self.party_client.decline,
            "start": self.party_client.start,
            "leave": self.party_client.leave,
            "cancel": self.party_client.cancel,
            "end": self.party_client.end,
        }
        operation = operations.get(action)
        if operation is None:
            self._party_request_failed(action, "不支持的聚会操作")
            return
        operation(party_id)

    def _party_snapshot_received(self, payload: object) -> None:
        if self._party_dialog is not None:
            self._party_dialog.set_snapshot(payload)

    def _party_detail_received(self, _party_id: str, payload: object) -> None:
        if self._party_dialog is not None:
            self._party_dialog.set_detail(payload)

    def _party_mutation_succeeded(self, operation: str, payload: object) -> None:
        if self._party_dialog is not None:
            self._party_dialog.set_status(self._party_success_message(operation))
            if isinstance(payload, dict) and payload.get("party_id"):
                self._party_dialog.set_detail(payload)
        self.cloud_session.sync_now()
        QTimer.singleShot(150, self.party_client.refresh)
        QTimer.singleShot(250, self._sync_party_context)
        QTimer.singleShot(300, self.refresh_pending_items)

    @staticmethod
    def _party_success_message(operation: str) -> str:
        labels = {
            "party_create": "聚会已创建，可以邀请好友。",
            "party_accept": "已使用当前宠物接受聚会邀请。",
            "party_decline": "已谢绝聚会邀请。",
            "party_start": "聚会已经开始，全部成员保留在一个场景面板中。",
            "party_leave": "当前宠物已离开聚会并返回家中。",
            "party_cancel": "聚会已取消。",
            "party_end": "聚会已结束，仍在场宠物已返回家中。",
        }
        prefix = operation.split(":", 1)[0]
        if prefix == "party_invite":
            return "聚会邀请已发送。"
        if prefix == "party_interact":
            return "聚会互动已经记录。"
        return labels.get(prefix, "聚会操作已完成。")

    def _party_request_failed(self, _operation: str, message: str) -> None:
        if self._party_dialog is not None:
            self._party_dialog.set_busy(False)
            self._party_dialog.set_status(message, error=True)

    def _party_cloud_state_changed(self, state: str) -> None:
        self._refresh_party_action()
        state_value = str(getattr(state, "value", state))
        if state_value == "connected" and self._party_dialog is not None:
            QTimer.singleShot(300, self.party_client.refresh)
        elif state_value in {"offline", "disabled", "error"} and self._party_dialog is not None:
            self._party_dialog.set_status("云端未连接，聚会场景暂时只读。", error=True)

    def _refresh_party_action(self) -> None:
        identity = getattr(self.cloud_session, "identity", None)
        if hasattr(self, "party_action"):
            self.party_action.setEnabled(identity is not None)

    def _switch_pet(self, *args, **kwargs):
        result = super()._switch_pet(*args, **kwargs)
        QTimer.singleShot(0, self._sync_party_context)
        return result

    def quit(self) -> None:
        if self._quitting:
            return
        if self._party_dialog is not None:
            self._party_dialog.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return PartyApplication().start(smoke_test_ms=smoke_test_ms)
