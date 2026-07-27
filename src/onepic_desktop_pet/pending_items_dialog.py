"""Compact desktop dialog for account-level pending customer tasks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


_KIND_LABELS = {
    "friend_request": "好友申请",
    "caregiver_invitation": "共同照料",
    "visit_request": "串门申请",
    "reminder_due": "到期提醒",
}
_ACTION_LABELS = {
    "accept": "接受",
    "reject": "拒绝",
    "complete": "完成",
    "snooze": "10 分钟后提醒",
    "dismiss": "忽略",
}


class PendingItemsDialog(QDialog):
    action_requested = Signal(str, str, str, int)
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cards: list[QFrame] = []
        self.setWindowTitle("待处理事项")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(620, 560)
        self.setMinimumSize(500, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        heading = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("待处理事项")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #344054;")
        self.summary_label = QLabel("正在读取好友、共同照料、串门和提醒…")
        self.summary_label.setStyleSheet("color: #667085;")
        copy.addWidget(title)
        copy.addWidget(self.summary_label)
        heading.addLayout(copy, 1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(refresh)
        root.addLayout(heading)

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

        self.status_label = QLabel("所有操作都会立即同步到 Web 和其他桌面设备。")
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
        urgent_count: int = 0,
    ) -> None:
        self._clear_cards()
        self.summary_label.setText(
            f"共 {max(0, int(total_count))} 项"
            + (f"，其中 {max(0, int(urgent_count))} 项优先处理" if urgent_count else "")
        )
        values = list(items)
        if not values:
            empty = QFrame()
            empty.setStyleSheet(
                "QFrame { background: #f8fafc; border: 1px solid #eaecf0; "
                "border-radius: 10px; padding: 18px; }"
            )
            layout = QVBoxLayout(empty)
            label = QLabel("当前没有需要处理的事项。")
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
        card = QFrame()
        urgent = str(item.get("priority") or "normal") == "urgent"
        card.setStyleSheet(
            "QFrame { background: %s; border: 1px solid %s; border-radius: 11px; }"
            % (("#fff8f5", "#f3b4a2") if urgent else ("white", "#e4e7ec"))
        )
        root = QVBoxLayout(card)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(7)

        kind = str(item.get("kind") or "")
        kind_label = QLabel(_KIND_LABELS.get(kind, kind or "待处理"))
        kind_label.setStyleSheet("color: #8a5b4b; font-size: 12px; font-weight: 700;")
        title = QLabel(str(item.get("title") or "待处理事项"))
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: 800; color: #344054;")
        detail = QLabel(str(item.get("detail") or ""))
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #667085;")
        root.addWidget(kind_label)
        root.addWidget(title)
        root.addWidget(detail)

        meta_parts: list[str] = []
        pet_name = str(item.get("pet_name") or "")
        if pet_name:
            meta_parts.append(f"宠物：{pet_name}")
        due = str(item.get("due_at") or item.get("occurred_at") or "")
        if due:
            meta_parts.append(due.replace("T", " ")[:16])
        if meta_parts:
            meta = QLabel(" · ".join(meta_parts))
            meta.setStyleSheet("color: #98a2b3; font-size: 11px;")
            root.addWidget(meta)

        actions_layout = QHBoxLayout()
        actions_layout.addStretch(1)
        kind_value = str(item.get("kind") or "")
        item_id = str(item.get("item_id") or "")
        actions = item.get("actions")
        for raw_action in actions if isinstance(actions, list) else []:
            action = str(raw_action)
            button = QPushButton(_ACTION_LABELS.get(action, action))
            if action in {"reject", "dismiss"}:
                button.setStyleSheet("color: #667085;")
            button.clicked.connect(
                lambda _checked=False, k=kind_value, i=item_id, a=action: self.action_requested.emit(
                    k, i, a, 10
                )
            )
            actions_layout.addWidget(button)
        root.addLayout(actions_layout)
        return card
