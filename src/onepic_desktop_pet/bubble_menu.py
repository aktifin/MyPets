"""桌面桌宠快捷环形/弧形气泡交互菜单模块。

本模块提供点击桌面宠物身旁时弹出的卡哇伊快捷气泡菜单（PetBubbleMenu），
包含摸摸、喂食、聊天、打卡、状态 5 个圆钮快捷操作，并支持自动优雅淡出。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QPushButton, QWidget


class PetBubbleMenu(QWidget):
    """卡哇伊桌面快捷气泡交互菜单。"""

    # 信号：动作指令 'touch' / 'feed' / 'chat' / 'checkin' / 'stats'
    action_triggered = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(260, 60)

        # 阴影效果
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setColor(Qt.GlobalColor.darkGray)
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # 5 大快捷圆钮
        buttons_info = [
            ("🖐️", "摸摸", "touch"),
            ("🍖", "喂食", "feed"),
            ("💬", "聊天", "chat"),
            ("🍵", "打卡", "checkin"),
            ("📊", "状态", "stats"),
        ]

        for emoji, tooltip, action_code in buttons_info:
            btn = QPushButton(emoji, self)
            btn.setToolTip(tooltip)
            btn.setFixedSize(40, 40)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #FFFFFF;
                    border: 2px solid #FFB6C1;
                    border-radius: 20px;
                    font-size: 16px;
                }
                QPushButton:hover {
                    background-color: #FFE4EC;
                    border: 2.5px solid #FF4081;
                }
                QPushButton:pressed {
                    background-color: #FFC0CB;
                }
            """)
            btn.clicked.connect(lambda _, code=action_code: self._on_btn_clicked(code))
            layout.addWidget(btn)

        # 3 秒无操作自动关闭定时器
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setInterval(3000)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self.hide)

    def popup_at(self, global_pos: QPoint) -> None:
        """在坐标处优雅显示气泡菜单。"""
        self.move(global_pos.x() - self.width() // 2, global_pos.y() - self.height() - 10)
        self.show()
        self.raise_()
        self.activateWindow()
        self._auto_close_timer.start()

    def _on_btn_clicked(self, action_code: str) -> None:
        self.action_triggered.emit(action_code)
        self.hide()
