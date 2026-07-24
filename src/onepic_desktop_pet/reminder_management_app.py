"""Reminder management composition root with explicit MyReminder synchronization."""

from __future__ import annotations

from PySide6.QtGui import QAction

from .myreminder_sync import MyReminderSyncController
from .reminder_app import ReminderDesktopPetApplication
from .reminder_manager import ReminderManagerDialog


class ManagedReminderDesktopPetApplication(ReminderDesktopPetApplication):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.myreminder_sync = MyReminderSyncController(
            self.cloud_session,
            self.cloud_api,
            parent=self.qt_app,
        )
        self._reminder_manager: ReminderManagerDialog | None = None

        self.reminder_manager_action = QAction("提醒管理…", self.tray_menu)
        self.reminder_manager_action.triggered.connect(self.open_reminder_manager)
        self.tray_menu.insertAction(self.message_action, self.reminder_manager_action)

        self.myreminder_sync.sync_started.connect(self._myreminder_sync_started)
        self.myreminder_sync.sync_succeeded.connect(self._myreminder_sync_succeeded)
        self.myreminder_sync.sync_failed.connect(self._myreminder_sync_failed)
        self.reminder_cloud.reminders_changed.connect(self._refresh_reminder_manager)
        self.reminder_cloud.account_changed.connect(
            lambda _account_id: self._refresh_reminder_manager()
        )

    def open_reminder_manager(self) -> None:
        if self._reminder_manager is None:
            self._reminder_manager = ReminderManagerDialog(self.reminder_cache)
            self._reminder_manager.sync_requested.connect(self.myreminder_sync.sync)
            self._reminder_manager.refresh_requested.connect(self.reminder_cloud.refresh)
            self._reminder_manager.complete_requested.connect(self.reminder_cloud.complete)
            self._reminder_manager.snooze_requested.connect(self.reminder_cloud.snooze)
            self._reminder_manager.dismiss_requested.connect(self.reminder_cloud.dismiss)
            self._reminder_manager.show_due_requested.connect(self.open_reminders)
        self._refresh_reminder_manager()
        self._reminder_manager.show()
        self._reminder_manager.raise_()
        self._reminder_manager.activateWindow()
        self.reminder_cloud.refresh()

    def _refresh_reminder_manager(self) -> None:
        if self._reminder_manager is None:
            return
        identity = self.cloud_session.identity
        self._reminder_manager.set_account(
            identity.account_id if identity else None,
            identity.display_name if identity else "",
        )
        if self._reminder_manager.isVisible():
            self._reminder_manager.refresh_from_cache()

    def _myreminder_sync_started(self) -> None:
        if self._reminder_manager is not None:
            self._reminder_manager.set_busy(True, "正在从 MyReminder 同步重复规则…")

    def _myreminder_sync_succeeded(self, payload: object) -> None:
        if not isinstance(payload, dict):
            self._myreminder_sync_failed("MyReminder 同步结果无效")
            return
        message = (
            "同步完成："
            f"拉取 {payload.get('pulled', 0)}，"
            f"新增 {payload.get('created', 0)}，"
            f"更新 {payload.get('updated', 0)}，"
            f"停用过期 {payload.get('expired', 0)}。"
        )
        if self._reminder_manager is not None:
            self._reminder_manager.set_busy(False, message)
        self.tray.setToolTip(f"{self.active_pet.identity.name} · {message}")
        self.reminder_cloud.refresh()

    def _myreminder_sync_failed(self, message: str) -> None:
        if self._reminder_manager is not None:
            self._reminder_manager.set_busy(False)
            self._reminder_manager.set_status(message, error=True)
        self.tray.setToolTip(
            f"{self.active_pet.identity.name} · MyReminder 同步失败：{message}"
        )

    def quit(self) -> None:
        if self._quitting:
            return
        if self._reminder_manager is not None:
            self._reminder_manager.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return ManagedReminderDesktopPetApplication().start(smoke_test_ms=smoke_test_ms)
