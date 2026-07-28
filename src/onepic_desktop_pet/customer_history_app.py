"""Final desktop composition layer for customer processing history."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction

from .actionable_visit_dialog import ActionableVisitDialog
from .customer_actions_app import CustomerActionsApplication
from .customer_history_client import CustomerHistoryClient
from .customer_history_dialog import CustomerHistoryDialog


class CustomerHistoryApplication(CustomerActionsApplication):
    """Add one read-only history center over existing customer workflows."""

    def __init__(self, *args, **kwargs) -> None:
        self._customer_history_dialog: CustomerHistoryDialog | None = None
        super().__init__(*args, **kwargs)
        self.customer_history_client = CustomerHistoryClient(
            self.cloud_session,
            self.cloud_api,
            parent=self.qt_app,
        )
        self.customer_history_client.history_received.connect(self._customer_history_received)
        self.customer_history_client.request_failed.connect(self._customer_history_failed)
        self.cloud_session.state_changed.connect(self._customer_history_cloud_state)

        menu = self.system_tray_menu.menu
        self.customer_history_action = QAction("处理记录…", menu)
        self.customer_history_action.triggered.connect(self.open_customer_history_dialog)
        separator = next((action for action in menu.actions() if action.isSeparator()), None)
        if separator is not None:
            menu.insertAction(separator, self.customer_history_action)
        else:
            menu.addAction(self.customer_history_action)
        self._refresh_customer_history_action()

    def open_customer_history_dialog(self) -> None:
        if self._customer_history_dialog is None:
            dialog = CustomerHistoryDialog()
            dialog.refresh_requested.connect(self.refresh_customer_history)
            dialog.detail_requested.connect(self._open_customer_history_detail)
            self._customer_history_dialog = dialog
        self._customer_history_dialog.show()
        self._customer_history_dialog.raise_()
        self._customer_history_dialog.activateWindow()
        kind, days = self._customer_history_dialog.current_filters()
        self.refresh_customer_history(kind, days)

    def refresh_customer_history(self, kind: str = "all", days: int = 30) -> None:
        if self._customer_history_dialog is not None:
            self._customer_history_dialog.set_busy(True)
        started = self.customer_history_client.refresh(kind=kind, days=days, limit=200)
        if not started and self._customer_history_dialog is not None and not self.cloud_session.connected:
            self._customer_history_dialog.set_busy(False)

    def _customer_history_received(self, payload: object) -> None:
        if self._customer_history_dialog is None:
            return
        self._customer_history_dialog.set_history(payload)

    def _customer_history_failed(self, message: str) -> None:
        if self._customer_history_dialog is not None:
            self._customer_history_dialog.set_busy(False)
            self._customer_history_dialog.set_status(message, error=True)

    def _open_customer_history_detail(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        target_kind = str(payload.get("target_kind") or "")
        target_id = str(payload.get("target_id") or "")
        if target_kind == "visit" and target_id:
            self.open_visit_dialog()
            if isinstance(self._visit_dialog, ActionableVisitDialog):
                self._visit_dialog.focus_visit(target_id)
            self.customer_navigation_client.load_timeline(target_id)
            return
        if target_kind == "reminder":
            opener = getattr(self, "open_reminder_manager", None)
            if callable(opener):
                opener()
                return
        if target_kind in {"friend", "shared_care"}:
            self.open_social_dialog()
            return
        if self._customer_history_dialog is not None:
            self._customer_history_dialog.set_status("相关详情当前不可打开。", error=True)

    def _customer_history_cloud_state(self, state: str) -> None:
        state_value = str(getattr(state, "value", state))
        self._refresh_customer_history_action()
        if state_value == "connected" and self._customer_history_dialog is not None:
            kind, days = self._customer_history_dialog.current_filters()
            QTimer.singleShot(400, lambda: self.refresh_customer_history(kind, days))

    def _refresh_customer_history_action(self) -> None:
        identity = getattr(self.cloud_session, "identity", None)
        self.customer_history_action.setEnabled(identity is not None)

    def quit(self) -> None:
        if self._quitting:
            return
        if self._customer_history_dialog is not None:
            self._customer_history_dialog.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return CustomerHistoryApplication().start(smoke_test_ms=smoke_test_ms)
