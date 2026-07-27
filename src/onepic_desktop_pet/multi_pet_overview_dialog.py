"""Desktop multi-pet status overview with explicit switch and care actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_PRIORITY_LABELS = {
    "urgent": "优先关注",
    "attention": "需要照料",
    "routine": "今日陪伴",
    "stable": "状态良好",
    "unavailable": "暂不可照料",
}


class MultiPetOverviewDialog(QDialog):
    switch_requested = Signal(str)
    care_requested = Signal(str, str)
    next_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cards: list[QFrame] = []
        self.setWindowTitle("多宠状态总览")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(700, 620)
        self.setMinimumSize(540, 440)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        heading = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("多宠状态总览")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #344054;")
        self.summary_label = QLabel("正在整理每只宠物的状态和今日任务…")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #667085;")
        copy.addWidget(title)
        copy.addWidget(self.summary_label)
        heading.addLayout(copy, 1)
        self.next_button = QPushButton("切换下一只需要照料")
        self.next_button.clicked.connect(self.next_requested.emit)
        heading.addWidget(self.next_button)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(refresh)
        root.addLayout(heading)

        explanation = QLabel(
            "状态明显偏低的宠物优先；状态稳定但今日任务未完成的进入日常轮换。"
            "串门、只读关系、冷却或达到日上限时不会被推荐为可立即照料。"
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(
            "background: #f8fafc; border-radius: 9px; padding: 9px; color: #475467;"
        )
        root.addWidget(explanation)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self.items_layout = QVBoxLayout(container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(10)
        self.items_layout.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        self.status_label = QLabel("所有切换只影响当前设备；照料仍由原有权限和冷却规则校验。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #667085;")
        root.addWidget(self.status_label)

        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.hide)
        root.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)

    def set_items(
        self,
        items: Sequence[Mapping[str, object]],
        *,
        total_count: int,
        needs_attention_count: int,
        urgent_count: int,
        next_pet_id: str | None,
    ) -> None:
        self._clear_cards()
        if total_count <= 0:
            summary = "当前没有可显示的宠物"
        elif needs_attention_count:
            summary = f"共 {total_count} 只，其中 {needs_attention_count} 只需要关注"
            if urgent_count:
                summary += f"，{urgent_count} 只优先处理"
        else:
            summary = f"共 {total_count} 只，当前状态都比较稳定"
        self.summary_label.setText(summary)
        self.next_button.setEnabled(bool(next_pet_id))
        self.next_button.setText(
            "切换下一只需要照料" if next_pet_id else "暂无其他待照料宠物"
        )

        values = list(items)
        if not values:
            empty = QFrame()
            empty.setStyleSheet(
                "QFrame { background: #f8fafc; border: 1px solid #eaecf0; "
                "border-radius: 10px; padding: 18px; }"
            )
            layout = QVBoxLayout(empty)
            label = QLabel("创建或同步更多宠物后，会在这里统一显示状态。")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #667085;")
            layout.addWidget(label)
            self.items_layout.insertWidget(0, empty)
            self._cards.append(empty)
            return

        for item in values:
            card = self._build_card(item)
            self.items_layout.insertWidget(self.items_layout.count() - 1, card)
            self._cards.append(card)

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: #b42318;" if error else "color: #067647;"
        )

    def _clear_cards(self) -> None:
        for card in self._cards:
            self.items_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    def _build_card(self, item: Mapping[str, object]) -> QFrame:
        priority = str(item.get("priority") or "stable")
        current = bool(item.get("current"))
        card = QFrame()
        background, border = {
            "urgent": ("#fff8f5", "#f1a58f"),
            "attention": ("#fffbf3", "#edc08c"),
            "unavailable": ("#f8fafc", "#e4e7ec"),
        }.get(priority, ("white", "#e4e7ec"))
        if current:
            border = "#d48a9b"
        card.setStyleSheet(
            f"QFrame {{ background: {background}; border: 1px solid {border}; "
            "border-radius: 11px; }}"
        )
        root = QVBoxLayout(card)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(7)

        header = QHBoxLayout()
        name = QLabel(str(item.get("name") or "宠物"))
        name.setStyleSheet("font-size: 16px; font-weight: 800; color: #344054;")
        meta = QLabel(
            f"Lv.{int(item.get('growth_level') or 1)} · "
            f"羁绊 Lv.{int(item.get('bond_level') or 1)}"
        )
        meta.setStyleSheet("color: #98a2b3;")
        identity = QVBoxLayout()
        identity.addWidget(name)
        identity.addWidget(meta)
        header.addLayout(identity, 1)
        badge_text = _PRIORITY_LABELS.get(priority, priority)
        if current:
            badge_text += " · 当前"
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            "background: #f2f4f7; color: #475467; border-radius: 9px; "
            "padding: 5px 9px; font-weight: 700;"
        )
        header.addWidget(badge)
        root.addLayout(header)

        status = QLabel(str(item.get("status_summary") or "状态正常"))
        status.setWordWrap(True)
        status.setStyleSheet("font-weight: 700; color: #344054;")
        detail = QLabel(str(item.get("recommendation_detail") or ""))
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #667085;")
        root.addWidget(status)
        root.addWidget(detail)

        completed = max(0, int(item.get("daily_completed_tasks") or 0))
        total = max(1, int(item.get("daily_total_tasks") or 3))
        task_row = QHBoxLayout()
        task = QLabel(
            f"今日任务 {completed}/{total}"
            + (" · 已完成" if bool(item.get("daily_all_completed")) else "")
        )
        task.setStyleSheet("color: #475467;")
        progress = QProgressBar()
        progress.setRange(0, total)
        progress.setValue(min(total, completed))
        progress.setTextVisible(False)
        progress.setMaximumWidth(220)
        progress.setStyleSheet(
            "QProgressBar { min-height: 7px; max-height: 7px; border: 0; "
            "border-radius: 3px; background: #eaecf0; }"
            "QProgressBar::chunk { border-radius: 3px; background: #d56f86; }"
        )
        task_row.addWidget(task)
        task_row.addWidget(progress, 1)
        root.addLayout(task_row)

        actions = QHBoxLayout()
        actions.addStretch(1)
        pet_id = str(item.get("pet_id") or "")
        if not current:
            switch_button = QPushButton("切换到它")
            switch_button.clicked.connect(
                lambda _checked=False, value=pet_id: self.switch_requested.emit(value)
            )
            actions.addWidget(switch_button)
        else:
            current_label = QLabel("当前宠物")
            current_label.setStyleSheet("color: #667085; font-weight: 700;")
            actions.addWidget(current_label)

        action = str(item.get("recommended_action") or "")
        if action and bool(item.get("can_care")):
            care_button = QPushButton(str(item.get("recommended_action_label") or "照料"))
            care_button.setEnabled(bool(item.get("action_available")))
            care_button.setToolTip(
                str(item.get("action_reason") or item.get("recommendation_detail") or "")
            )
            care_button.clicked.connect(
                lambda _checked=False, value=pet_id, action_code=action: self.care_requested.emit(
                    value, action_code
                )
            )
            actions.addWidget(care_button)
        root.addLayout(actions)
        return card
