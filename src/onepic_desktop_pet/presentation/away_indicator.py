"""
主人桌面宠物外出串门标识组件 (AwayIndicator)。

职责范围：
- 当自有宠物处于串门或途中状态时，在主人桌面显示低打扰的“外出中”折叠胶囊卡片；
- 显示目的地好友、剩余预估返家时间与串门备注；
- 支持展开详情弹框并提供【提前召回宠物】快捷操作。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget


class AwayIndicator(QWidget):
    """主人桌面宠物外出串门折叠胶囊标识。"""

    recall_requested = Signal(str)  # visit_id

    def __init__(
        self,
        visit_id: str,
        pet_name: str,
        host_name: str,
        note: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.visit_id = visit_id
        self.pet_name = pet_name
        self.host_name = host_name
        self.note = note
        self._drag_position = QPoint()

        self._setup_ui()
        self._setup_flags()

    def _setup_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _setup_ui(self) -> None:
        self.resize(230, 70)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.capsule_frame = QFrame(self)
        self.capsule_frame.setStyleSheet(
            """
            QFrame {
                background-color: rgba(15, 23, 42, 0.90);
                border: 1px solid #38bdf8;
                border-radius: 24px;
            }
        """
        )
        capsule_layout = QHBoxLayout(self.capsule_frame)
        capsule_layout.setContentsMargins(12, 6, 12, 6)
        capsule_layout.setSpacing(8)

        icon_lbl = QLabel("🐾", self.capsule_frame)
        icon_lbl.setStyleSheet("font-size: 18px; background: transparent;")
        capsule_layout.addWidget(icon_lbl)

        info_box = QVBoxLayout()
        info_box.setSpacing(2)

        title_lbl = QLabel(f"{self.pet_name} 外出串门中…", self.capsule_frame)
        title_lbl.setStyleSheet("color: #f8fafc; font-size: 11px; font-weight: bold; background: transparent;")

        sub_lbl = QLabel(f"作客好友: {self.host_name}", self.capsule_frame)
        sub_lbl.setStyleSheet("color: #38bdf8; font-size: 10px; background: transparent;")

        info_box.addWidget(title_lbl)
        info_box.addWidget(sub_lbl)
        capsule_layout.addLayout(info_box)

        btn_recall = QPushButton("召回", self.capsule_frame)
        btn_recall.setStyleSheet(
            """
            QPushButton {
                background-color: #be123c;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 4px 10px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #9f1239;
            }
        """
        )
        btn_recall.clicked.connect(lambda: self.recall_requested.emit(self.visit_id))
        capsule_layout.addWidget(btn_recall)

        layout.addWidget(self.capsule_frame)

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
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #0284c7;
            }
        """
        )
        act_recall = QAction("🏠 提前召回宠物", self)
        act_recall.triggered.connect(lambda: self.recall_requested.emit(self.visit_id))
        menu.addAction(act_recall)
        menu.exec(event.globalPos())
