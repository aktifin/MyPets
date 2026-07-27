"""Non-blocking prompt shown after a confirmed care action."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NextPetPrompt(QFrame):
    """Offer an explicit switch to the next pet without changing selection automatically."""

    switch_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__(None)
        self._pet_id = ""
        self.setObjectName("nextPetPrompt")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(300)
        self.setMaximumWidth(410)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 13, 16, 13)
        root.setSpacing(7)
        self.title_label = QLabel("还有宠物需要关注")
        self.title_label.setObjectName("nextPetPromptTitle")
        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        self.detail_label.setObjectName("nextPetPromptDetail")
        root.addWidget(self.title_label)
        root.addWidget(self.detail_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.dismiss_button = QPushButton("稍后")
        self.dismiss_button.setObjectName("nextPetPromptDismiss")
        self.switch_button = QPushButton("切换")
        self.switch_button.setObjectName("nextPetPromptSwitch")
        actions.addWidget(self.dismiss_button)
        actions.addWidget(self.switch_button)
        root.addLayout(actions)

        self.dismiss_button.clicked.connect(self.hide)
        self.switch_button.clicked.connect(self._emit_switch)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.setStyleSheet(
            "QFrame#nextPetPrompt { background: #f4f7ff; border: 1px solid #bfd0ff; "
            "border-radius: 14px; }"
            "QLabel#nextPetPromptTitle { color: #26448b; font-size: 14px; font-weight: 800; }"
            "QLabel#nextPetPromptDetail { color: #475467; }"
            "QPushButton { min-height: 28px; padding: 3px 12px; border-radius: 8px; }"
            "QPushButton#nextPetPromptSwitch { background: #365bb4; color: white; border: none; }"
            "QPushButton#nextPetPromptDismiss { background: white; color: #475467; "
            "border: 1px solid #cbd5e1; }"
        )

    def show_for(
        self,
        anchor: QWidget,
        *,
        pet_id: str,
        pet_name: str,
        reason: str,
        duration_ms: int = 12000,
    ) -> None:
        self._pet_id = pet_id
        self.title_label.setText(f"下一只可以看看 {pet_name}")
        self.detail_label.setText(reason)
        self.switch_button.setText(f"切换到 {pet_name}")
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
        self._timer.start(max(2500, int(duration_ms)))

    def _emit_switch(self) -> None:
        if not self._pet_id:
            return
        pet_id = self._pet_id
        self.hide()
        self.switch_requested.emit(pet_id)
