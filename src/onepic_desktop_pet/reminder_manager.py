"""User-facing reminder list, provider sync, and occurrence actions."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .domain import ReminderOccurrence, ReminderOccurrenceState
from .reminder_cache import ReminderCache


class ReminderManagerDialog(QDialog):
    sync_requested = Signal()
    refresh_requested = Signal()
    complete_requested = Signal(str)
    snooze_requested = Signal(str, int)
    dismiss_requested = Signal(str)
    show_due_requested = Signal()

    def __init__(
        self,
        cache: ReminderCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache = cache
        self.account_id: str | None = None
        self.display_name = ""
        self.setWindowTitle("MyPets 提醒管理")
        self.setModal(False)
        self.resize(760, 460)

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.account_label = QLabel("尚未登录")
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("未来与待处理", "upcoming")
        self.filter_combo.addItem("历史记录", "history")
        self.filter_combo.addItem("全部", "all")
        self.filter_combo.currentIndexChanged.connect(self.refresh_from_cache)
        self.sync_button = QPushButton("同步 MyReminder")
        self.sync_button.clicked.connect(self.sync_requested)
        self.refresh_button = QPushButton("刷新缓存")
        self.refresh_button.clicked.connect(self._refresh_clicked)
        header.addWidget(self.account_label)
        header.addStretch(1)
        header.addWidget(self.filter_combo)
        header.addWidget(self.refresh_button)
        header.addWidget(self.sync_button)
        root.addLayout(header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["时间", "标题", "状态", "来源", "分类"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.complete_button = QPushButton("完成")
        self.complete_button.clicked.connect(self._complete)
        self.snooze_5_button = QPushButton("贪睡 5 分钟")
        self.snooze_5_button.clicked.connect(lambda: self._snooze(5))
        self.snooze_10_button = QPushButton("贪睡 10 分钟")
        self.snooze_10_button.clicked.connect(lambda: self._snooze(10))
        self.snooze_30_button = QPushButton("贪睡 30 分钟")
        self.snooze_30_button.clicked.connect(lambda: self._snooze(30))
        self.dismiss_button = QPushButton("忽略")
        self.dismiss_button.clicked.connect(self._dismiss)
        self.show_due_button = QPushButton("显示到期提醒卡")
        self.show_due_button.clicked.connect(self.show_due_requested)
        actions.addWidget(self.complete_button)
        actions.addWidget(self.snooze_5_button)
        actions.addWidget(self.snooze_10_button)
        actions.addWidget(self.snooze_30_button)
        actions.addWidget(self.dismiss_button)
        actions.addStretch(1)
        actions.addWidget(self.show_due_button)
        root.addLayout(actions)

        self.status_label = QLabel("提醒由服务端同步，桌面端负责可靠投递。")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self._set_action_enabled(False)

    def set_account(self, account_id: str | None, display_name: str = "") -> None:
        self.account_id = account_id.strip() if account_id else None
        self.display_name = display_name.strip()
        self.account_label.setText(
            f"账户：{self.display_name or self.account_id}"
            if self.account_id
            else "尚未登录"
        )
        self.sync_button.setEnabled(bool(self.account_id))
        self.refresh_from_cache()

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.sync_button.setEnabled(bool(self.account_id) and not busy)
        self.refresh_button.setEnabled(not busy)
        if message:
            self.set_status(message)

    def set_status(self, message: str, *, error: bool = False) -> None:
        prefix = "错误：" if error else ""
        self.status_label.setText(f"{prefix}{message}")
        self.status_label.setProperty("error", error)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def refresh_from_cache(self) -> None:
        selected_id = self.selected_occurrence_id()
        self.table.setRowCount(0)
        if not self.account_id:
            self._set_action_enabled(False)
            return
        values = self.cache.list_for_account(self.account_id, limit=1000)
        mode = self.filter_combo.currentData()
        filtered = [item for item in values if self._matches_filter(item, mode)]
        for row, occurrence in enumerate(filtered):
            self.table.insertRow(row)
            scheduled = occurrence.scheduled_at.astimezone().strftime("%Y-%m-%d %H:%M")
            time_item = QTableWidgetItem(scheduled)
            time_item.setData(Qt.ItemDataRole.UserRole, occurrence.occurrence_id)
            self.table.setItem(row, 0, time_item)
            self.table.setItem(row, 1, QTableWidgetItem(occurrence.title))
            self.table.setItem(
                row,
                2,
                QTableWidgetItem(self._state_label(occurrence.state)),
            )
            self.table.setItem(row, 3, QTableWidgetItem(occurrence.source))
            self.table.setItem(row, 4, QTableWidgetItem(occurrence.category))
            if occurrence.occurrence_id == selected_id:
                self.table.selectRow(row)
        self.table.resizeColumnsToContents()
        if self.table.rowCount() and not self.table.selectedItems():
            self.table.selectRow(0)
        self._selection_changed()

    def selected_occurrence_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    def _selected_occurrence(self) -> ReminderOccurrence | None:
        occurrence_id = self.selected_occurrence_id()
        return self.cache.get(occurrence_id) if occurrence_id else None

    def _selection_changed(self) -> None:
        occurrence = self._selected_occurrence()
        actionable = bool(
            occurrence
            and occurrence.state
            in {
                ReminderOccurrenceState.PENDING,
                ReminderOccurrenceState.DELIVERED,
            }
        )
        self._set_action_enabled(actionable)

    def _set_action_enabled(self, enabled: bool) -> None:
        self.complete_button.setEnabled(enabled)
        self.snooze_5_button.setEnabled(enabled)
        self.snooze_10_button.setEnabled(enabled)
        self.snooze_30_button.setEnabled(enabled)
        self.dismiss_button.setEnabled(enabled)

    def _refresh_clicked(self) -> None:
        self.refresh_from_cache()
        self.refresh_requested.emit()

    def _complete(self) -> None:
        occurrence_id = self.selected_occurrence_id()
        if occurrence_id:
            self.complete_requested.emit(occurrence_id)

    def _snooze(self, minutes: int) -> None:
        occurrence_id = self.selected_occurrence_id()
        if occurrence_id:
            self.snooze_requested.emit(occurrence_id, minutes)

    def _dismiss(self) -> None:
        occurrence_id = self.selected_occurrence_id()
        if occurrence_id:
            self.dismiss_requested.emit(occurrence_id)

    @staticmethod
    def _matches_filter(occurrence: ReminderOccurrence, mode: object) -> bool:
        if mode == "upcoming":
            return occurrence.state in {
                ReminderOccurrenceState.PENDING,
                ReminderOccurrenceState.DELIVERED,
            }
        if mode == "history":
            return occurrence.state in {
                ReminderOccurrenceState.COMPLETED,
                ReminderOccurrenceState.DISMISSED,
                ReminderOccurrenceState.EXPIRED,
            }
        return True

    @staticmethod
    def _state_label(state: ReminderOccurrenceState) -> str:
        return {
            ReminderOccurrenceState.PENDING: "待处理",
            ReminderOccurrenceState.DELIVERED: "已投递",
            ReminderOccurrenceState.SEEN: "已查看",
            ReminderOccurrenceState.SNOOZED: "已贪睡",
            ReminderOccurrenceState.COMPLETED: "已完成",
            ReminderOccurrenceState.DISMISSED: "已忽略",
            ReminderOccurrenceState.EXPIRED: "已过期",
        }.get(state, state.value)
