"""
接待端桌面访客宠物窗口 (GuestPetWindow)。

职责范围：
- 在接待方桌面建立独立于主宠物窗口的透明桌面访客 QWidget；
- 不读取、不访问本机的提醒、私人数据与聊天记忆；
- 渲染访客宠物形象与动态表情，并在资产缺失时提供优雅名片降级；
- 右键菜单支持【发送访客宠物返家】与友好互动打招呼；
- 允许鼠标左键按住拖拽在桌面上任意定位。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QContextMenuEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget


class GuestPetWindow(QWidget):
    """独立的桌面访客宠物窗口。"""

    send_guest_home_requested = Signal(str)  # visit_id
    guest_interacted = Signal(str)  # action_name

    def __init__(
        self,
        visit_id: str,
        visitor_pet_id: str,
        visitor_pet_name: str,
        visitor_owner_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.visit_id = visit_id
        self.visitor_pet_id = visitor_pet_id
        self.visitor_pet_name = visitor_pet_name
        self.visitor_owner_name = visitor_owner_name
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
        self.resize(220, 240)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 气泡对话框
        self.speech_bubble = QLabel("🐾 来串门啦！", self)
        self.speech_bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speech_bubble.setStyleSheet(
            """
            QLabel {
                background-color: rgba(15, 23, 42, 0.88);
                color: #38bdf8;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 12px;
                font-family: "Microsoft YaHei", sans-serif;
                font-size: 11px;
                font-weight: bold;
            }
        """
        )
        layout.addWidget(self.speech_bubble)

        # 访客形象主卡片
        self.card_frame = QFrame(self)
        self.card_frame.setStyleSheet(
            """
            QFrame {
                background-color: rgba(30, 41, 59, 0.92);
                border: 2px solid #0284c7;
                border-radius: 14px;
            }
        """
        )
        card_layout = QVBoxLayout(self.card_frame)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(6)

        self.avatar_label = QLabel(self.card_frame)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setText("🐶")
        self.avatar_label.setStyleSheet("font-size: 42px; background: transparent;")
        card_layout.addWidget(self.avatar_label)

        self.name_label = QLabel(self.visitor_pet_name, self.card_frame)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet(
            "color: #f8fafc; font-size: 13px; font-weight: bold; background: transparent;"
        )
        card_layout.addWidget(self.name_label)

        self.owner_label = QLabel(f"主人: {self.visitor_owner_name}", self.card_frame)
        self.owner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.owner_label.setStyleSheet("color: #94a3b8; font-size: 10px; background: transparent;")
        card_layout.addWidget(self.owner_label)

        layout.addWidget(self.card_frame)

    def set_avatar_pixmap(self, pixmap: QPixmap) -> None:
        """从资产加载缩放渲染访客宠物形象。"""
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                90, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.avatar_label.setPixmap(scaled)

    def speak(self, text: str) -> None:
        """显示短暂互动气泡对话。"""
        self.speech_bubble.setText(text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.speak("汪！很高兴来到你的桌面作客～")
            self.guest_interacted.emit("greet")
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

        act_greet = QAction("🐾 打招呼", self)
        act_greet.triggered.connect(lambda: self.speak("👋 摸摸头～亲密度 +1！"))

        act_send_home = QAction("🏠 发送访客宠物提前返家", self)
        act_send_home.triggered.connect(
            lambda: self.send_guest_home_requested.emit(self.visit_id)
        )

        menu.addAction(act_greet)
        menu.addSeparator()
        menu.addAction(act_send_home)
        menu.exec(event.globalPos())
