"""A non-activating reminder card shown next to the desktop pet or away indicator."""

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
from .reminder_resume import ReminderResumeSummary


class ReminderCard(QFrame):
    complete_requested = Signal(str)
    snooze_requested = Signal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
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
        self.setMaximumWidth(440)
        self._queue: list[ReminderOccurrence] = []
        self._resume_summary: ReminderResumeSummary | None = None
        self._build_ui()

    @property
    def current_occurrence_id(self) -> str | None:
        if self._resume_summary is not None:
            return None
        return self._queue[0].occurrence_id if self._queue else None

    @property
    def showing_resume_summary(self) -> bool:
        return self._resume_summary is not None

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
        self.review_button = QPushButton("逐条处理")
        self.review_button.clicked.connect(self._review_resume_items)
        self.review_button.hide()
        actions.addWidget(self.review_button)

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
        self._resume_summary = None
        self.review_button.hide()
        self.complete_button.show()
        self.snooze_button.show()
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

    def show_resume_summary(self, summary: ReminderResumeSummary) -> None:
        """Show one low-interruption card instead of replaying every missed reminder."""

        self._resume_summary = summary
        known = {item.occurrence_id for item in self._queue}
        for occurrence in summary.occurrences:
            if occurrence.occurrence_id not in known:
                self._queue.append(occurrence)
                known.add(occurrence.occurrence_id)
        self.review_button.show()
        self.complete_button.hide()
        self.snooze_button.hide()
        self.title_label.setText(f"休眠期间错过 {summary.count} 条提醒")
        preview = [item.title for item in summary.occurrences[:3]]
        remaining = summary.count - len(preview)
        lines = [f"• {title}" for title in preview]
        if remaining > 0:
            lines.append(f"• 另有 {remaining} 条")
        self.content_label.setText("\n".join(lines))
        first = summary.first_due_at.astimezone().strftime("%m-%d %H:%M")
        last = summary.last_due_at.astimezone().strftime("%m-%d %H:%M")
        due_range = first if first == last else f"{first} 至 {last}"
        gap_minutes = max(1, summary.gap_seconds // 60)
        self.meta_label.setText(f"错过时段：{due_range} · 系统暂停约 {gap_minutes} 分钟")
        self.status_label.setText(
            "已合并为一张恢复摘要，不会连续播放多个提醒动画。"
        )
        self.show()

    def resolve(self, occurrence_id: str) -> None:
        self._queue = [
            item for item in self._queue if item.occurrence_id != occurrence_id
        ]
        if self._resume_summary is not None:
            remaining = tuple(
                item
                for item in self._resume_summary.occurrences
                if item.occurrence_id != occurrence_id
            )
            self._resume_summary = (
                ReminderResumeSummary(
                    occurrences=remaining,
                    previous_scan_at=self._resume_summary.previous_scan_at,
                    resumed_at=self._resume_summary.resumed_at,
                )
                if remaining
                else None
            )
        if self._queue:
            if self._resume_summary is not None:
                self.show_resume_summary(self._resume_summary)
            else:
                self._render_current()
                self.show()
        else:
            self._resume_summary = None
            self.hide()

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #b91c1c;" if error else "color: #555;")

    def _review_resume_items(self) -> None:
        self._resume_summary = None
        self.review_button.hide()
        self.complete_button.show()
        self.snooze_button.show()
        if self._queue:
            self._render_current()
            self.show()
        else:
            self.hide()

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
