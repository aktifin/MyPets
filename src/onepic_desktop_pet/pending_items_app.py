"""Desktop composition layer for the unified customer pending-items queue."""

from __future__ import annotations

from PySide6.QtCore import QTimer

from .growth_experience_app import GrowthExperienceApplication
from .pending_items_client import PendingItemsCloudClient
from .pending_items_dialog import PendingItemsDialog


class PendingItemsApplication(GrowthExperienceApplication):
    """Add one account-level queue for social requests, visits and reminders."""

    def __init__(self, *args, **kwargs) -> None:
        self._pending_items_payload: dict[str, object] = {
            "count": 0,
            "urgent_count": 0,
            "items": [],
        }
        self._pending_items_dialog: PendingItemsDialog | None = None
        super().__init__(*args, **kwargs)
        self.pending_items_client = PendingItemsCloudClient(
            self.cloud_api,
            parent=self.qt_app,
        )
        self.pending_items_client.items_received.connect(self._pending_items_received)
        self.pending_items_client.action_succeeded.connect(self._pending_action_succeeded)
        self.pending_items_client.request_failed.connect(self._pending_items_failed)
        self.cloud_session.state_changed.connect(self._pending_cloud_state_changed)

        self._pending_items_timer = QTimer(self.qt_app)
        self._pending_items_timer.setInterval(5 * 60 * 1000)
        self._pending_items_timer.timeout.connect(self.refresh_pending_items)
        if self.cloud_session.connected:
            QTimer.singleShot(600, self.refresh_pending_items)

    def pending_items_count(self) -> int:
        return max(0, int(self._pending_items_payload.get("count") or 0))

    def pending_urgent_count(self) -> int:
        return max(0, int(self._pending_items_payload.get("urgent_count") or 0))

    def open_pending_items_dialog(self) -> None:
        if self._pending_items_dialog is None:
            dialog = PendingItemsDialog()
            dialog.refresh_requested.connect(self.refresh_pending_items)
            dialog.action_requested.connect(self._act_on_pending_item)
            self._pending_items_dialog = dialog
        self._sync_pending_items_dialog()
        self._pending_items_dialog.show()
        self._pending_items_dialog.raise_()
        self._pending_items_dialog.activateWindow()
        self.refresh_pending_items()

    def refresh_pending_items(self) -> None:
        if not self.cloud_session.connected:
            if self._pending_items_dialog is not None:
                self._pending_items_dialog.set_status(
                    "请先连接云端账户，再读取待处理事项。",
                    error=True,
                )
            return
        self.pending_items_client.refresh(limit=100)

    def _pending_cloud_state_changed(self, state: str) -> None:
        if state == "connected":
            QTimer.singleShot(500, self.refresh_pending_items)
            return
        self._pending_items_payload = {"count": 0, "urgent_count": 0, "items": []}
        self._sync_pending_items_dialog()
        self.system_tray_menu.refresh()

    def _pending_items_received(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self._pending_items_payload = dict(payload)
        self._sync_pending_items_dialog()
        self.system_tray_menu.refresh()

    def _act_on_pending_item(
        self,
        kind: str,
        item_id: str,
        action: str,
        snooze_minutes: int,
    ) -> None:
        if self._pending_items_dialog is not None:
            self._pending_items_dialog.set_status("正在处理…")
        self.pending_items_client.act(
            kind=kind,
            item_id=item_id,
            action=action,
            snooze_minutes=snooze_minutes,
        )

    def _pending_action_succeeded(self, payload: object) -> None:
        message = "待处理事项已更新。"
        if isinstance(payload, dict) and payload.get("message"):
            message = str(payload["message"])
        if self._pending_items_dialog is not None:
            self._pending_items_dialog.set_status(message)
        self.cloud_session.sync_now()
        self.refresh_pending_items()

    def _pending_items_failed(self, operation: str, message: str) -> None:
        if self._pending_items_dialog is not None:
            self._pending_items_dialog.set_status(message, error=True)
        if operation == "list":
            self.system_tray_menu.refresh()

    def _sync_pending_items_dialog(self) -> None:
        if self._pending_items_dialog is None:
            return
        raw_items = self._pending_items_payload.get("items")
        items = raw_items if isinstance(raw_items, list) else []
        self._pending_items_dialog.set_items(
            [item for item in items if isinstance(item, dict)],
            total_count=self.pending_items_count(),
            urgent_count=self.pending_urgent_count(),
        )

    def start(self, smoke_test_ms: int | None = None) -> int:
        if smoke_test_ms is None:
            self._pending_items_timer.start()
        return super().start(smoke_test_ms=smoke_test_ms)

    def quit(self) -> None:
        if self._quitting:
            return
        self._pending_items_timer.stop()
        if self._pending_items_dialog is not None:
            self._pending_items_dialog.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return PendingItemsApplication().start(smoke_test_ms=smoke_test_ms)
