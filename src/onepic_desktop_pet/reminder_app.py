"""Reminder-enabled desktop application composition root."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction

from .app import DesktopPetApplication
from .domain import NotificationKind, ReminderOccurrenceState
from .reminder_cache import ReminderCache
from .reminder_card import ReminderCard
from .reminder_cloud import ReminderCloudController
from .reminder_scheduler import ReminderScheduler


class ReminderDesktopPetApplication(DesktopPetApplication):
    """Add reliable local reminder delivery without coupling it to the base pet lifecycle."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.reminder_cache = ReminderCache(self.local_store)
        self.reminder_cloud = ReminderCloudController(
            self.cloud_api,
            self.cloud_session,
            self.reminder_cache,
            self.qt_app,
        )
        self.reminder_scheduler = ReminderScheduler(
            self.reminder_cache,
            parent=self.qt_app,
        )
        self.reminder_card = ReminderCard(self.window)

        self.reminder_scheduler.reminders_due.connect(self._show_due_reminders)
        self.reminder_scheduler.delivery_requested.connect(self.reminder_cloud.deliver)
        self.reminder_cloud.account_changed.connect(self._reminder_account_changed)
        self.reminder_cloud.reminders_changed.connect(self._reminders_changed)
        self.reminder_cloud.status_message.connect(self._reminder_status)
        self.reminder_cloud.action_synced.connect(self._reminder_action_synced)
        self.reminder_cloud.action_failed.connect(self._reminder_action_failed)
        self.reminder_card.complete_requested.connect(self._complete_reminder)
        self.reminder_card.snooze_requested.connect(self._snooze_reminder)

        self.reminder_action = QAction("⏰ 提醒", self.tray_menu)
        self.reminder_action.triggered.connect(self.open_reminders)
        self.tray_menu.insertAction(self.message_action, self.reminder_action)
        self._reminders_changed()

    def _reminder_account_changed(self, account_id: str) -> None:
        if account_id:
            if self.reminder_scheduler.account_id != account_id:
                self.reminder_scheduler.start(account_id)
            else:
                self.reminder_scheduler.scan()
        else:
            self.reminder_scheduler.stop()
            self.reminder_card.hide()
        self._refresh_reminder_action()

    def _reminders_changed(self) -> None:
        account_id = self.reminder_cloud.account_id
        if account_id:
            if self.reminder_scheduler.account_id != account_id:
                self.reminder_scheduler.start(account_id)
            else:
                self.reminder_scheduler.scan()
        self._refresh_reminder_action()

    def _refresh_reminder_action(self) -> None:
        account_id = self.reminder_cloud.account_id
        unread = 0
        if account_id:
            unread = self.local_store.unread_counts(account_id).get(
                NotificationKind.REMINDER,
                0,
            )
        self.reminder_action.setText(
            f"⏰ 提醒 ({unread})" if unread else "⏰ 提醒"
        )

    def open_reminders(self) -> None:
        account_id = self.reminder_cloud.account_id
        if not account_id:
            self.tray.setToolTip(f"{self.active_pet.identity.name} · 请先登录云端账户")
            return
        due = self.reminder_scheduler.scan()
        delivered = self.reminder_cache.list_for_account(
            account_id,
            states={ReminderOccurrenceState.DELIVERED},
        )
        values = due or delivered
        if values:
            self._show_due_reminders(values)
        else:
            self.tray.setToolTip(f"{self.active_pet.identity.name} · 当前没有到期提醒")

    def _show_due_reminders(self, occurrences: object) -> None:
        if not isinstance(occurrences, list) or not occurrences:
            return
        self.reminder_card.show_occurrences(occurrences)
        self.reminder_card.adjustSize()
        self._position_reminder_card()
        self._refresh_reminder_action()

    def _position_reminder_card(self) -> None:
        window_geometry = self.window.frameGeometry()
        card_size = self.reminder_card.sizeHint()
        screen = self.window.screen()
        available = screen.availableGeometry() if screen is not None else window_geometry
        right_x = window_geometry.right() + 12
        left_x = window_geometry.left() - card_size.width() - 12
        x = right_x if right_x + card_size.width() <= available.right() else left_x
        x = max(available.left(), min(x, available.right() - card_size.width()))
        y = max(
            available.top(),
            min(window_geometry.top(), available.bottom() - card_size.height()),
        )
        self.reminder_card.move(QPoint(x, y))

    def _complete_reminder(self, occurrence_id: str) -> None:
        if self.reminder_cloud.complete(occurrence_id):
            self.reminder_card.resolve(occurrence_id)
            self.reminder_card.set_status("已在本机完成，正在同步云端。")
            self._refresh_reminder_action()

    def _snooze_reminder(self, occurrence_id: str, minutes: int) -> None:
        if self.reminder_cloud.snooze(occurrence_id, minutes):
            self.reminder_card.resolve(occurrence_id)
            self.reminder_card.set_status(
                f"已在本机贪睡 {minutes} 分钟，正在同步云端。"
            )
            self._refresh_reminder_action()

    def _reminder_status(self, message: str) -> None:
        if message:
            self.tray.setToolTip(f"{self.active_pet.identity.name} · {message}")

    def _reminder_action_synced(self, action: str, occurrence_id: str) -> None:
        label = {
            "delivered": "提醒投递已同步",
            "completed": "完成状态已同步",
            "snoozed": "贪睡时间已同步",
            "dismissed": "忽略状态已同步",
        }.get(action, "提醒状态已同步")
        if self.reminder_card.current_occurrence_id == occurrence_id:
            self.reminder_card.set_status(label)
        self._refresh_reminder_action()

    def _reminder_action_failed(
        self,
        action: str,
        occurrence_id: str,
        message: str,
    ) -> None:
        if self.reminder_card.current_occurrence_id == occurrence_id:
            self.reminder_card.set_status(message, error=True)
        self.tray.setToolTip(f"{self.active_pet.identity.name} · 提醒同步失败：{message}")

    def quit(self) -> None:
        if self._quitting:
            return
        self.reminder_scheduler.stop()
        self.reminder_card.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return ReminderDesktopPetApplication().start(smoke_test_ms=smoke_test_ms)
