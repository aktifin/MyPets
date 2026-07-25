"""Friends and shared-care composition root layered on reminders and messaging."""

from __future__ import annotations

from PySide6.QtGui import QAction

from .pet_registry import LOCAL_ACCOUNT_ID
from .reminder_management_app import ManagedReminderDesktopPetApplication
from .social_client import SocialController
from .social_dialog import SocialDialog


class SocialDesktopPetApplication(ManagedReminderDesktopPetApplication):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.social_controller = SocialController(
            self.cloud_session,
            self.cloud_api,
            parent=self.qt_app,
        )
        self._social_dialog: SocialDialog | None = None
        self._known_friend_request_ids: set[str] = set()
        self._known_caregiver_invitation_ids: set[str] = set()
        self.social_action = QAction("好友与共同照料…", self.tray_menu)
        self.social_action.triggered.connect(self.open_social_dialog)
        self.tray_menu.insertAction(self.reminder_manager_action, self.social_action)

        self.social_controller.snapshot_changed.connect(self._social_snapshot_changed)
        self.social_controller.status_message.connect(self._social_status)
        self.social_controller.operation_failed.connect(self._social_failed)
        self.social_controller.pets_sync_requested.connect(self.cloud_session.sync_now)
        self.cloud_session.state_changed.connect(lambda _state: self._refresh_social_context())

    def open_social_dialog(self) -> None:
        if self._social_dialog is None:
            dialog = SocialDialog()
            dialog.refresh_requested.connect(
                lambda: self.social_controller.refresh(self._managed_active_pet_id())
            )
            dialog.friend_request_requested.connect(self.social_controller.send_friend_request)
            dialog.friend_request_action_requested.connect(
                self.social_controller.respond_friend_request
            )
            dialog.friend_remove_requested.connect(self.social_controller.remove_friend)
            dialog.block_requested.connect(self.social_controller.block)
            dialog.unblock_requested.connect(self.social_controller.unblock)
            dialog.privacy_save_requested.connect(self.social_controller.update_privacy)
            dialog.caregiver_invite_requested.connect(
                self.social_controller.invite_caregiver
            )
            dialog.caregiver_invitation_action_requested.connect(
                self.social_controller.respond_caregiver_invitation
            )
            dialog.caregiver_remove_requested.connect(
                self.social_controller.remove_caregiver
            )
            self._social_dialog = dialog
        self._refresh_social_context()
        self._social_dialog.show()
        self._social_dialog.raise_()
        self._social_dialog.activateWindow()
        self.social_controller.refresh(self._managed_active_pet_id())

    def _current_relation_role(self) -> str | None:
        identity = self.cloud_session.identity
        if identity is None:
            return None
        for relation in self.local_store.list_relations(self.active_pet.identity.pet_id):
            if relation.account_id == identity.account_id:
                return relation.role.value
        return None

    def _managed_active_pet_id(self) -> str | None:
        if self.active_pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID:
            return None
        return (
            self.active_pet.identity.pet_id
            if self._current_relation_role() in {"owner", "co_owner"}
            else None
        )

    def _refresh_social_context(self) -> None:
        if self._social_dialog is None:
            return
        identity = self.cloud_session.identity
        active_is_cloud = self.active_pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID
        can_manage = self._managed_active_pet_id() is not None
        self._social_dialog.set_context(
            account_id=identity.account_id if identity else None,
            display_name=identity.display_name if identity else "",
            active_pet_id=self.active_pet.identity.pet_id if active_is_cloud else None,
            active_pet_name=self.active_pet.identity.name if active_is_cloud else "",
            can_manage_pet=can_manage,
        )
        self.social_controller.active_pet_id = self._managed_active_pet_id()

    def _social_snapshot_changed(self, snapshot: object) -> None:
        if self._social_dialog is not None:
            self._social_dialog.apply_snapshot(snapshot)
        if not isinstance(snapshot, dict):
            return
        requests = snapshot.get("requests")
        invitations = snapshot.get("invitations")
        incoming_requests = requests.get("incoming", []) if isinstance(requests, dict) else []
        incoming_invitations = (
            invitations.get("incoming", []) if isinstance(invitations, dict) else []
        )
        request_ids = {
            str(item.get("request_id"))
            for item in incoming_requests
            if isinstance(item, dict) and item.get("request_id")
        }
        invitation_ids = {
            str(item.get("invitation_id"))
            for item in incoming_invitations
            if isinstance(item, dict) and item.get("invitation_id")
        }
        new_requests = request_ids - self._known_friend_request_ids
        new_invitations = invitation_ids - self._known_caregiver_invitation_ids
        self._known_friend_request_ids = request_ids
        self._known_caregiver_invitation_ids = invitation_ids
        if new_requests:
            self.tray.showMessage(
                "MyPets 好友",
                f"收到 {len(new_requests)} 个新的好友申请，可在托盘菜单中处理。",
            )
        if new_invitations:
            self.tray.showMessage(
                "MyPets 共同照料",
                f"收到 {len(new_invitations)} 个新的共同照料邀请。",
            )

    def _social_status(self, message: str) -> None:
        if self._social_dialog is not None:
            self._social_dialog.set_status(message)
        self.tray.setToolTip(f"{self.active_pet.identity.name} · {message}")

    def _social_failed(self, message: str) -> None:
        if self._social_dialog is not None:
            self._social_dialog.set_status(message, error=True)
        self.tray.setToolTip(
            f"{self.active_pet.identity.name} · 好友或共同照料操作失败：{message}"
        )

    def _pets_changed(self) -> None:
        super()._pets_changed()
        self._refresh_social_context()
        if self._social_dialog is not None and self._social_dialog.isVisible():
            self.social_controller.refresh(self._managed_active_pet_id())

    def quit(self) -> None:
        if self._quitting:
            return
        if self._social_dialog is not None:
            self._social_dialog.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return SocialDesktopPetApplication().start(smoke_test_ms=smoke_test_ms)
