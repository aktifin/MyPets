"""Low-distraction indicator shown while the selected pet is visiting a friend."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget


class AwayIndicator(QWidget):
    recall_requested = Signal(str)

    def __init__(
        self,
        visit_id: str,
        pet_name: str,
        host_name: str,
        note: str = "",
        scheduled_end_at: datetime | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.visit_id = visit_id
        self.pet_name = pet_name
        self.host_name = host_name
        self.note = note
        self.scheduled_end_at = self._aware(scheduled_end_at)
        self._drag_position = QPoint()
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._update_remaining)

        self._setup_flags()
        self._setup_ui()
        self._update_remaining()
        if self.scheduled_end_at is not None:
            self._countdown_timer.start()

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def _setup_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _setup_ui(self) -> None:
        self.setFixedSize(246, 78)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        frame = QFrame(self)
        frame.setStyleSheet(
            "QFrame { background: rgba(15,23,42,230); border: 1px solid #38bdf8; "
            "border-radius: 25px; }"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 6, 10, 6)
        row.setSpacing(8)

        icon = QLabel("🐾", frame)
        icon.setStyleSheet("font-size: 18px; background: transparent;")
        row.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(1)
        title = QLabel(f"{self.pet_name} 外出串门中", frame)
        title.setStyleSheet(
            "color: #f8fafc; font-size: 11px; font-weight: 600; background: transparent;"
        )
        self.detail_label = QLabel(frame)
        self.detail_label.setStyleSheet(
            "color: #38bdf8; font-size: 9px; background: transparent;"
        )
        self.detail_label.setToolTip(self.note or "没有串门留言")
        info.addWidget(title)
        info.addWidget(self.detail_label)
        row.addLayout(info, 1)

        recall = QPushButton("召回", frame)
        recall.setStyleSheet(
            "QPushButton { background: #be123c; color: white; border: none; "
            "border-radius: 10px; padding: 4px 9px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background: #9f1239; }"
        )
        recall.clicked.connect(lambda: self.recall_requested.emit(self.visit_id))
        row.addWidget(recall)
        layout.addWidget(frame)

    def _update_remaining(self) -> None:
        suffix = "返家时间待同步"
        if self.scheduled_end_at is not None:
            remaining = int(
                (self.scheduled_end_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()
            )
            if remaining <= 0:
                suffix = "正在确认返家状态"
                self._countdown_timer.stop()
            else:
                minutes, seconds = divmod(remaining, 60)
                hours, minutes = divmod(minutes, 60)
                suffix = (
                    f"预计 {hours:d}:{minutes:02d}:{seconds:02d} 后返家"
                    if hours
                    else f"预计 {minutes:d}:{seconds:02d} 后返家"
                )
        self.detail_label.setText(f"接待：{self.host_name} · {suffix}")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        recall = QAction("提前召回宠物", menu)
        recall.triggered.connect(
            lambda _checked=False: self.recall_requested.emit(self.visit_id)
        )
        menu.addAction(recall)
        menu.exec(event.globalPos())

    def closeEvent(self, event: QCloseEvent) -> None:
        self._countdown_timer.stop()
        super().closeEvent(event)
