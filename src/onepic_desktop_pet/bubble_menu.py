"""Contextual quick-care panel shown when the desktop pet is clicked."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PetBubbleMenu(QWidget):
    """A compact customer-facing home panel anchored beside the pet."""

    action_triggered = Signal(str)
    about_to_show = Signal()

    CARE_BUTTONS = (
        ("🍖", "投喂", "feed"),
        ("🎾", "玩耍", "play"),
        ("🫧", "清洁", "clean"),
        ("🖐️", "摸摸", "touch"),
        ("🌙", "休息", "rest"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._recommended_action = "pet"
        self.setObjectName("petQuickPanel")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(390)
        self.setMaximumWidth(440)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(Qt.GlobalColor.darkGray)
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

        card = QFrame(self)
        card.setObjectName("petQuickCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        identity = QVBoxLayout()
        identity.setSpacing(2)
        self.name_label = QLabel("我的宠物")
        self.name_label.setObjectName("petQuickName")
        self.level_label = QLabel("Lv.1 · 初生期")
        self.level_label.setObjectName("petQuickMeta")
        identity.addWidget(self.name_label)
        identity.addWidget(self.level_label)
        self.presence_label = QLabel("在家")
        self.presence_label.setObjectName("petQuickPresence")
        self.presence_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addLayout(identity, 1)
        header.addWidget(self.presence_label)
        root.addLayout(header)

        self.status_label = QLabel("状态良好，可以轻松互动")
        self.status_label.setObjectName("petQuickStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        progress_row = QHBoxLayout()
        self.daily_label = QLabel("今日任务 0 / 3 · 连续 0 天")
        self.daily_label.setObjectName("petQuickDaily")
        self.daily_progress = QProgressBar()
        self.daily_progress.setObjectName("petQuickProgress")
        self.daily_progress.setRange(0, 3)
        self.daily_progress.setValue(0)
        self.daily_progress.setTextVisible(False)
        progress_row.addWidget(self.daily_label)
        progress_row.addWidget(self.daily_progress, 1)
        root.addLayout(progress_row)

        self.task_label = QLabel("○ 3 次照料  ·  ○ 2 种方式  ·  ○ 1 次陪伴")
        self.task_label.setObjectName("petQuickTasks")
        self.task_label.setWordWrap(True)
        root.addWidget(self.task_label)

        self.recommendation_button = QPushButton("现在建议：摸摸它")
        self.recommendation_button.setObjectName("petQuickRecommendation")
        self.recommendation_button.clicked.connect(self._run_recommendation)
        root.addWidget(self.recommendation_button)

        care_grid = QGridLayout()
        care_grid.setHorizontalSpacing(7)
        care_grid.setVerticalSpacing(7)
        self.action_buttons: dict[str, QPushButton] = {}
        for column, (emoji, label, action_code) in enumerate(self.CARE_BUTTONS):
            button = QPushButton(f"{emoji}\n{label}")
            button.setObjectName("petQuickCare")
            button.setToolTip(label)
            button.setMinimumSize(60, 54)
            button.clicked.connect(
                lambda _checked=False, code=action_code: self._on_btn_clicked(code)
            )
            care_grid.addWidget(button, 0, column)
            self.action_buttons[action_code] = button
        root.addLayout(care_grid)

        secondary = QHBoxLayout()
        for label, action_code in (
            ("💬 聊天", "chat"),
            ("🍵 健康打卡", "checkin"),
            ("📊 完整状态", "stats"),
        ):
            button = QPushButton(label)
            button.setObjectName("petQuickSecondary")
            button.clicked.connect(
                lambda _checked=False, code=action_code: self._on_btn_clicked(code)
            )
            secondary.addWidget(button)
        root.addLayout(secondary)

        self.hint_label = QLabel("完成全部任务可点亮今日陪伴徽章。")
        self.hint_label.setObjectName("petQuickHint")
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)

        self.setStyleSheet(
            "QFrame#petQuickCard { background: rgba(255,250,246,248); border: 1px solid #f0d8dd; "
            "border-radius: 18px; }"
            "QLabel#petQuickName { font-size: 18px; font-weight: 800; color: #263238; }"
            "QLabel#petQuickMeta, QLabel#petQuickDaily, QLabel#petQuickHint { color: #667085; }"
            "QLabel#petQuickTasks { color: #475467; background: #f8f4f1; border-radius: 9px; "
            "padding: 7px 9px; }"
            "QLabel#petQuickPresence { background: #edf8f1; color: #256447; border-radius: 9px; "
            "padding: 5px 9px; font-weight: 700; }"
            "QLabel#petQuickStatus { background: white; border-radius: 10px; padding: 9px 11px; "
            "color: #344054; }"
            "QProgressBar#petQuickProgress { min-height: 8px; max-height: 8px; border: 0; "
            "border-radius: 4px; background: #f0e7e8; }"
            "QProgressBar#petQuickProgress::chunk { border-radius: 4px; background: #e66b84; }"
            "QPushButton { border: 1px solid #ead4d9; border-radius: 10px; background: white; "
            "padding: 7px 10px; color: #344054; }"
            "QPushButton:hover { background: #fff0f3; border-color: #e7a9b5; }"
            "QPushButton:disabled { color: #98a2b3; background: #f2f4f7; border-color: #eaecf0; }"
            "QPushButton#petQuickRecommendation { min-height: 38px; background: #e66b84; color: white; "
            "border: 0; font-weight: 800; text-align: left; padding-left: 14px; }"
            "QPushButton#petQuickRecommendation:disabled { background: #e5d5d8; color: #7c6870; }"
            "QPushButton#petQuickCare { font-weight: 700; }"
            "QPushButton#petQuickSecondary { color: #475467; }"
        )

        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setInterval(12000)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self.hide)

    def set_context(
        self,
        *,
        pet_name: str,
        level_text: str,
        presence_text: str,
        status_text: str,
        recommendation_action: str | None,
        recommendation_text: str,
        recommendation_detail: str,
        daily_count: int,
        daily_goal: int,
        can_care: bool,
        streak_days: int = 0,
        task_text: str = "",
        reward_text: str = "",
        action_states: Mapping[str, tuple[bool, str]] | None = None,
    ) -> None:
        self.name_label.setText(pet_name)
        self.level_label.setText(level_text)
        self.presence_label.setText(presence_text)
        self.status_label.setText(status_text)
        self._recommended_action = recommendation_action or ""
        normalized_states = dict(action_states or {})
        recommendation_state = normalized_states.get(self._recommended_action)
        recommendation_available = (
            recommendation_state[0] if recommendation_state is not None else can_care
        )
        recommendation_reason = (
            recommendation_state[1] if recommendation_state is not None else recommendation_detail
        )
        if recommendation_state is not None and not recommendation_available:
            self.recommendation_button.setText(recommendation_reason)
        else:
            self.recommendation_button.setText(f"现在建议：{recommendation_text}")
        self.recommendation_button.setToolTip(recommendation_reason)
        self.recommendation_button.setEnabled(
            bool(recommendation_action and can_care and recommendation_available)
        )
        safe_goal = max(1, int(daily_goal))
        safe_count = max(0, min(safe_goal, int(daily_count)))
        self.daily_label.setText(
            f"今日任务 {safe_count} / {safe_goal} · 连续 {max(0, int(streak_days))} 天"
        )
        self.daily_progress.setRange(0, safe_goal)
        self.daily_progress.setValue(safe_count)
        self.task_label.setText(task_text or "○ 3 次照料  ·  ○ 2 种方式  ·  ○ 1 次陪伴")
        for button_code, button in self.action_buttons.items():
            action = "pet" if button_code == "touch" else button_code
            state = normalized_states.get(action)
            enabled = can_care and (state[0] if state is not None else True)
            reason = state[1] if state is not None else recommendation_detail
            button.setEnabled(enabled)
            button.setToolTip(reason)
        self.hint_label.setText(
            recommendation_detail
            if not can_care
            else (reward_text or "完成全部任务可点亮今日陪伴徽章。")
        )

    def popup_at(self, global_pos: QPoint) -> None:
        self.about_to_show.emit()
        self.adjustSize()
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        x = global_pos.x() - self.width() // 2
        y = global_pos.y() - self.height() - 10
        if area is not None:
            x = min(max(x, area.left()), area.right() - self.width() + 1)
            if y < area.top():
                y = min(area.bottom() - self.height() + 1, global_pos.y() + 10)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self._auto_close_timer.start()

    def _run_recommendation(self) -> None:
        if self._recommended_action:
            code = "touch" if self._recommended_action == "pet" else self._recommended_action
            self._on_btn_clicked(code)

    def _on_btn_clicked(self, action_code: str) -> None:
        self.action_triggered.emit(action_code)
        self.hide()
