"""Message drawer extension with explicit quick replies and related-detail navigation."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton

from .message_drawer import MessageDrawer


_QUICK_REPLIES = {
    "visit": ("收到，我来看看", "可以，稍后处理", "谢谢，宠物已经到家"),
    "shared_care": ("收到，我会留意", "好的，谢谢", "我稍后处理"),
    "friend_pet": ("好可爱", "收到啦", "下次一起玩"),
    "direct": ("收到", "好的，谢谢", "我稍后回复你"),
}


class ActionableMessageDrawer(MessageDrawer):
    """Keep normal typed messaging while adding optional customer replies."""

    related_detail_requested = Signal(str)

    def __init__(self, *args, **kwargs) -> None:
        self._quick_buttons: list[QPushButton] = []
        super().__init__(*args, **kwargs)

    def _build_ui(self) -> None:
        super()._build_ui()
        root = self.layout()
        if root is None:
            return

        quick_row = QHBoxLayout()
        quick_row.addStretch(1)
        for _index in range(3):
            button = QPushButton()
            button.setVisible(False)
            button.clicked.connect(
                lambda _checked=False, current=button: self._send_quick_reply(current.text())
            )
            quick_row.addWidget(button)
            self._quick_buttons.append(button)
        root.insertLayout(max(0, root.count() - 1), quick_row)

        self.related_button = QPushButton("查看相关详情")
        self.related_button.setVisible(False)
        self.related_button.clicked.connect(self._request_related_detail)
        root.insertWidget(max(0, root.count() - 1), self.related_button)

    def _render_selected(self) -> None:
        super()._render_selected()
        conversation_id = self._selected_conversation_id
        conversation = (
            self.cache.get_conversation(self.account_id, conversation_id)
            if self.account_id and conversation_id
            else None
        )
        writable = conversation is not None and conversation.kind == "direct"
        replies = _QUICK_REPLIES.get(
            conversation.category if conversation is not None else "direct",
            _QUICK_REPLIES["direct"],
        )
        for index, button in enumerate(self._quick_buttons):
            text = replies[index] if index < len(replies) else ""
            button.setText(text)
            button.setVisible(writable and bool(text))
            button.setEnabled(writable and bool(text))
        self.related_button.setVisible(conversation is not None)
        self.related_button.setEnabled(conversation is not None)

    def set_related_detail(self, label: str | None, *, enabled: bool = True) -> None:
        value = (label or "查看相关详情").strip()
        self.related_button.setText(value)
        self.related_button.setVisible(bool(self._selected_conversation_id))
        self.related_button.setEnabled(bool(enabled and self._selected_conversation_id))

    def _send_quick_reply(self, text: str) -> None:
        value = text.strip()
        if not value:
            return
        self.message_input.setText(value)
        self._send_message()

    def _request_related_detail(self) -> None:
        conversation_id = self._selected_conversation_id
        if conversation_id:
            self.related_detail_requested.emit(conversation_id)
            self.set_status("正在读取相关详情…")
