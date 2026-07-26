"""Non-blocking near-pet feedback for confirmed customer actions."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget


class DesktopFeedbackToast(QFrame):
    """Show concise success or failure feedback beside the desktop pet."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setObjectName("desktopFeedbackToast")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(280)
        self.setMaximumWidth(390)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 13, 16, 13)
        root.setSpacing(4)
        self.title_label = QLabel()
        self.title_label.setObjectName("desktopFeedbackTitle")
        self.detail_label = QLabel()
        self.detail_label.setObjectName("desktopFeedbackDetail")
        self.detail_label.setWordWrap(True)
        root.addWidget(self.title_label)
        root.addWidget(self.detail_label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._apply_style(False)

    def _apply_style(self, error: bool) -> None:
        border = "#f5b7b1" if error else "#b7dfc7"
        background = "#fff3f1" if error else "#f0faf4"
        title = "#a2231d" if error else "#256447"
        self.setStyleSheet(
            f"QFrame#desktopFeedbackToast {{ background: {background}; border: 1px solid {border}; "
            "border-radius: 14px; }}"
            f"QLabel#desktopFeedbackTitle {{ color: {title}; font-size: 14px; font-weight: 800; }}"
            "QLabel#desktopFeedbackDetail { color: #475467; }"
        )

    def show_near(
        self,
        anchor: QWidget,
        title: str,
        detail: str,
        *,
        error: bool = False,
        duration_ms: int = 3200,
    ) -> None:
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self._apply_style(error)
        self.adjustSize()

        screen = QApplication.screenAt(anchor.frameGeometry().center()) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        gap = 10
        x = anchor.x() - self.width() - gap
        if area is not None and x < area.left():
            x = anchor.x() + anchor.width() + gap
        y = anchor.y() + max(0, (anchor.height() - self.height()) // 2)
        if area is not None:
            x = min(max(x, area.left()), area.right() - self.width() + 1)
            y = min(max(y, area.top()), area.bottom() - self.height() + 1)
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self._timer.start(max(800, int(duration_ms)))
