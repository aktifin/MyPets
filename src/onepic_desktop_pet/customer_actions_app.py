"""Final customer composition layer for visit timelines, quick replies, and detail navigation."""

from __future__ import annotations

from .actionable_message_drawer import ActionableMessageDrawer
from .actionable_pending_items_dialog import ActionablePendingItemsDialog
from .actionable_visit_dialog import ActionableVisitDialog
from .customer_navigation_client import CustomerNavigationClient
from .multi_pet_care_layout_app import MultiPetCareLayoutApplication
from .pet_registry import LOCAL_ACCOUNT_ID


class CustomerActionsApplication(MultiPetCareLayoutApplication):
    """Add navigation and message efficiency without replacing authoritative feature clients."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.customer_navigation_client = CustomerNavigationClient(
            self.cloud_session,
            self.cloud_api,
            parent=self.qt_app,
        )
        self.customer_navigation_client.timeline_received.connect(
            self._customer_timeline_received
        )
        self.customer_navigation_client.target_received.connect(
            self._customer_target_received
        )
        self.customer_navigation_client.request_failed.connect(
            self._customer_navigation_failed
        )

    def open_message_drawer(self) -> None:
        if self._message_drawer is None:
            drawer = ActionableMessageDrawer(self.cloud_session.message_cache)
            drawer.refresh_requested.connect(self.cloud_session.refresh_conversations)
            drawer.create_conversation_requested.connect(
                self.cloud_session.create_conversation
            )
            drawer.conversation_selected.connect(self.cloud_session.fetch_messages)
            drawer.send_requested.connect(self._send_message)
            drawer.read_requested.connect(self.cloud_session.mark_message_read)
            drawer.related_detail_requested.connect(
                self.customer_navigation_client.load_conversation_target
            )
            self._message_drawer = drawer
        identity = self.cloud_session.identity
        self._message_drawer.set_account(
            identity.account_id if identity else None,
            identity.display_name if identity else "",
        )
        self._message_drawer.show()
        self._message_drawer.raise_()
        self._message_drawer.activateWindow()
        if identity is not None:
            self.cloud_session.refresh_conversations()

    def open_visit_dialog(self) -> None:
        if self._visit_dialog is None:
            dialog = ActionableVisitDialog()
            dialog.refresh_requested.connect(
                lambda: self.visit_controller.refresh(self._visit_active_pet_id())
            )
            dialog.friend_pets_requested.connect(self.visit_controller.load_friend_pets)
            dialog.visit_request_requested.connect(self.visit_controller.request_visit)
            dialog.visit_action_requested.connect(self.visit_controller.respond_visit)
            dialog.visit_recall_requested.connect(self.visit_controller.recall_visit)
            dialog.timeline_requested.connect(
                self.customer_navigation_client.load_timeline
            )
            self._visit_dialog = dialog
        self._refresh_visit_context()
        self._visit_dialog.show()
        self._visit_dialog.raise_()
        self._visit_dialog.activateWindow()
        self.visit_controller.refresh(self._visit_active_pet_id())

    def open_pending_items_dialog(self) -> None:
        if self._pending_items_dialog is None:
            dialog = ActionablePendingItemsDialog()
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
        if not isinstance(payload, dict):
            return
        kind = str(payload.get("kind") or "")
        item_id = str(payload.get("item_id") or "")
        pet_id = str(payload.get("pet_id") or "")
        if kind == "visit_request" and item_id:
            self.open_visit_dialog()
            self.customer_navigation_client.load_timeline(item_id)
            return
        if kind == "reminder_due":
            opener = getattr(self, "open_reminder_manager", None)
            if callable(opener):
                opener()
            return
        if kind == "caregiver_invitation":
            if pet_id and self.local_store.get_pet(pet_id) is not None:
                self._switch_pet(pet_id)
            self.open_social_dialog()
            return
        if kind == "friend_request":
            self.open_social_dialog()

    def _customer_timeline_received(self, payload: object) -> None:
        if self._visit_dialog is None:
            self.open_visit_dialog()
        if isinstance(self._visit_dialog, ActionableVisitDialog):
            self._visit_dialog.show_timeline(payload)

    def _customer_target_received(self, conversation_id: str, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        kind = str(payload.get("kind") or "none")
        target_id = str(payload.get("target_id") or "")
        label = str(payload.get("label") or "查看相关详情")
        if isinstance(self._message_drawer, ActionableMessageDrawer):
            self._message_drawer.set_related_detail(label, enabled=kind != "none")
        if kind == "visit" and target_id:
            self.open_visit_dialog()
            if isinstance(self._visit_dialog, ActionableVisitDialog):
                self._visit_dialog.focus_visit(target_id)
            self.customer_navigation_client.load_timeline(target_id)
            return
        if kind == "pet" and target_id:
            pet = self.local_store.get_pet(target_id)
            if pet is None:
                self._set_message_navigation_status("相关宠物尚未同步到本机", error=True)
                return
            if (
                pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID
                and not self.cloud_session.connected
            ):
                self._set_message_navigation_status("云端未连接，暂时不能切换相关宠物", error=True)
                return
            self._switch_pet(target_id)
            self.open_pet_care_panel()
            return
        if kind == "friend":
            self.open_social_dialog()
            return
        self._set_message_navigation_status(label, error=kind == "none")

    def _set_message_navigation_status(self, message: str, *, error: bool = False) -> None:
        if self._message_drawer is not None:
            self._message_drawer.set_status(message, error=error)

    def _customer_navigation_failed(self, operation: str, message: str) -> None:
        if operation == "timeline" and self._visit_dialog is not None:
            self._visit_dialog.set_status(message, error=True)
        else:
            self._set_message_navigation_status(message, error=True)


def run(smoke_test_ms: int | None = None) -> int:
    return CustomerActionsApplication().start(smoke_test_ms=smoke_test_ms)
