"""A non-activating reminder card shown next to the desktop pet."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .domain import ReminderOccurrence


class ReminderCard(QFrame):
    complete_requested = Signal(str)
    snooze_requested = Signal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("reminderCard")
        self.setStyleSheet(
            """
            QFrame#reminderCard {
                background: rgba(255, 255, 255, 246);
                border: 1px solid rgba(80, 80, 80, 70);
                border-radius: 12px;
            }
            QLabel#reminderTitle { font-weight: 700; font-size: 14px; }
            QLabel#reminderMeta { color: #666; }
            QLabel#reminderStatus { color: #555; }
            """
        )
        self.setMinimumWidth(330)
        self.setMaximumWidth(420)
        self._queue: list[ReminderOccurrence] = []
        self._build_ui()

    @property
    def current_occurrence_id(self) -> str | None:
        return self._queue[0].occurrence_id if self._queue else None

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.title_label = QLabel("提醒")
        self.title_label.setObjectName("reminderTitle")
        header.addWidget(self.title_label, 1)
        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(26, 26)
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        root.addLayout(header)

        self.content_label = QLabel()
        self.content_label.setWordWrap(True)
        root.addWidget(self.content_label)

        self.meta_label = QLabel()
        self.meta_label.setObjectName("reminderMeta")
        self.meta_label.setWordWrap(True)
        root.addWidget(self.meta_label)

        actions = QHBoxLayout()
        self.complete_button = QPushButton("完成")
        self.complete_button.clicked.connect(self._complete)
        actions.addWidget(self.complete_button)

        self.snooze_button = QToolButton()
        self.snooze_button.setText("贪睡")
        self.snooze_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        snooze_menu = QMenu(self.snooze_button)
        for minutes in (5, 10, 30):
            action = snooze_menu.addAction(f"{minutes} 分钟")
            action.triggered.connect(
                lambda _checked=False, minutes=minutes: self._snooze(minutes)
            )
        self.snooze_button.setMenu(snooze_menu)
        actions.addWidget(self.snooze_button)
        actions.addStretch(1)
        root.addLayout(actions)

        self.status_label = QLabel("提醒在本机到点投递；操作会同步到云端。")
        self.status_label.setObjectName("reminderStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def show_occurrences(self, occurrences: list[ReminderOccurrence]) -> None:
        known = {item.occurrence_id for item in self._queue}
        for occurrence in occurrences:
            if occurrence.occurrence_id not in known:
                self._queue.append(occurrence)
                known.add(occurrence.occurrence_id)
        if not self._queue:
            self.hide()
            return
        self._render_current()
        self.show()

    def resolve(self, occurrence_id: str) -> None:
        self._queue = [
            item for item in self._queue if item.occurrence_id != occurrence_id
        ]
        if self._queue:
            self._render_current()
            self.show()
        else:
            self.hide()

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #b91c1c;" if error else "color: #555;")

    def _render_current(self) -> None:
        occurrence = self._queue[0]
        remaining = len(self._queue) - 1
        self.title_label.setText(
            occurrence.title if remaining == 0 else f"{occurrence.title} · 另有 {remaining} 条"
        )
        self.content_label.setText(occurrence.content or "到时间了。")
        local_time = occurrence.scheduled_at.astimezone().strftime("%Y-%m-%d %H:%M")
        self.meta_label.setText(
            f"{local_time} · {occurrence.category} · {occurrence.priority}"
        )
        self.status_label.setText(
            "多条逾期提醒已合并；处理当前项目后继续显示下一条。"
            if remaining
            else "提醒在本机到点投递；操作会同步到云端。"
        )

    def _complete(self) -> None:
        occurrence_id = self.current_occurrence_id
        if occurrence_id:
            self.complete_requested.emit(occurrence_id)

    def _snooze(self, minutes: int) -> None:
        occurrence_id = self.current_occurrence_id
        if occurrence_id:
            self.snooze_requested.emit(occurrence_id, minutes)
