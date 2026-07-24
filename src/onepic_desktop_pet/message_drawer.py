"""Low-interruption conversation drawer opened explicitly from the pet badge or tray."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .message_cache import MessageCache
from .messaging import ConversationRecord, MessageRecord


class MessageDrawer(QDialog):
    """Show cached conversations without stealing attention on incoming messages."""

    refresh_requested = Signal()
    create_conversation_requested = Signal(str)
    conversation_selected = Signal(str)
    send_requested = Signal(str, str)
    read_requested = Signal(str)

    def __init__(self, cache: MessageCache, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.account_id = ""
        self.display_name = ""
        self._selected_conversation_id: str | None = None
        self.setWindowTitle("MyPets 消息")
        self.resize(720, 480)
        self.setMinimumSize(600, 380)
        self.setModal(False)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.account_label = QLabel("尚未登录")
        header.addWidget(self.account_label, 1)
        self.recipient_input = QLineEdit()
        self.recipient_input.setPlaceholderText("输入精确用户名")
        self.recipient_input.setMaximumWidth(190)
        header.addWidget(self.recipient_input)
        self.create_button = QPushButton("新建私聊")
        self.create_button.clicked.connect(self._create_conversation)
        header.addWidget(self.create_button)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_requested)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.conversation_list = QListWidget()
        self.conversation_list.setMinimumWidth(210)
        self.conversation_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.conversation_list.currentItemChanged.connect(
            lambda current, _previous: self._select_conversation(current)
        )
        splitter.addWidget(self.conversation_list)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.conversation_title = QLabel("选择一个会话")
        self.conversation_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        detail_layout.addWidget(self.conversation_title)
        self.message_list = QListWidget()
        self.message_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.message_list.setWordWrap(True)
        detail_layout.addWidget(self.message_list, 1)
        compose = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("输入消息；内容仅在发送后进入云端")
        self.message_input.returnPressed.connect(self._send_message)
        compose.addWidget(self.message_input, 1)
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self._send_message)
        compose.addWidget(self.send_button)
        detail_layout.addLayout(compose)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self.status_label = QLabel("消息默认折叠，不会自动弹出。")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self._set_controls_enabled(False)

    def set_account(self, account_id: str | None, display_name: str = "") -> None:
        self.account_id = (account_id or "").strip()
        self.display_name = display_name.strip()
        if self.account_id:
            self.account_label.setText(self.display_name or "已登录")
            self._set_controls_enabled(True)
            self.refresh_from_cache()
        else:
            self.account_label.setText("尚未登录")
            self._set_controls_enabled(False)
            self.conversation_list.clear()
            self.message_list.clear()
            self.conversation_title.setText("请先登录云端账户")

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.recipient_input.setEnabled(enabled)
        self.create_button.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)
        self.message_input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)

    def refresh_from_cache(self) -> None:
        selected = self._selected_conversation_id
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        selected_item: QListWidgetItem | None = None
        if self.account_id:
            for conversation in self.cache.list_conversations(self.account_id):
                item = QListWidgetItem(self._conversation_label(conversation))
                item.setData(Qt.ItemDataRole.UserRole, conversation.conversation_id)
                item.setToolTip(self._conversation_tooltip(conversation))
                if conversation.unread_count:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.conversation_list.addItem(item)
                if conversation.conversation_id == selected:
                    selected_item = item
        self.conversation_list.blockSignals(False)
        if selected_item is not None:
            self.conversation_list.setCurrentItem(selected_item)
            self._render_selected()
        elif self.conversation_list.count() > 0:
            self.conversation_list.setCurrentRow(0)
        else:
            self._selected_conversation_id = None
            self.conversation_title.setText("暂无会话")
            self.message_list.clear()

    @staticmethod
    def _conversation_label(conversation: ConversationRecord) -> str:
        suffix = f"  💬 {conversation.unread_count}" if conversation.unread_count else ""
        return f"{conversation.title}{suffix}"

    @staticmethod
    def _conversation_tooltip(conversation: ConversationRecord) -> str:
        if conversation.last_message is None:
            return "尚无消息"
        return conversation.last_message.content

    def _select_conversation(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        conversation_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(conversation_id, str) or not conversation_id:
            return
        self._selected_conversation_id = conversation_id
        self._render_selected()
        self.conversation_selected.emit(conversation_id)
        conversation = self.cache.get_conversation(self.account_id, conversation_id)
        latest = self.cache.latest_message(self.account_id, conversation_id)
        if (
            conversation is not None
            and conversation.unread_count > 0
            and latest is not None
            and not latest.outgoing
        ):
            self.read_requested.emit(latest.message_id)

    def _render_selected(self) -> None:
        conversation_id = self._selected_conversation_id
        if not self.account_id or not conversation_id:
            return
        conversation = self.cache.get_conversation(self.account_id, conversation_id)
        self.conversation_title.setText(
            conversation.title if conversation is not None else "会话"
        )
        self.message_list.clear()
        for message in self.cache.list_messages(self.account_id, conversation_id):
            item = QListWidgetItem(self._message_text(message))
            if message.outgoing:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
                item.setForeground(QColor("#2563eb"))
            else:
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft)
            self.message_list.addItem(item)
        if self.message_list.count():
            self.message_list.scrollToBottom()

    @staticmethod
    def _message_text(message: MessageRecord) -> str:
        time_text = message.created_at.astimezone().strftime("%m-%d %H:%M")
        return f"{message.sender_display_name} · {time_text}\n{message.content}"

    def _create_conversation(self) -> None:
        username = self.recipient_input.text().strip()
        if not username:
            self.set_status("请输入收件人的精确用户名。", error=True)
            return
        self.create_conversation_requested.emit(username)
        self.set_status("正在创建会话…")

    def _send_message(self) -> None:
        conversation_id = self._selected_conversation_id
        content = self.message_input.text().strip()
        if not conversation_id:
            self.set_status("请先选择一个会话。", error=True)
            return
        if not content:
            self.set_status("消息内容不能为空。", error=True)
            return
        self.send_requested.emit(conversation_id, content)
        self.set_status("正在发送消息…")

    def set_status(
        self,
        message: str,
        *,
        error: bool = False,
        clear_message_input: bool = False,
        clear_recipient_input: bool = False,
    ) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: #b91c1c;" if error else "color: palette(text);"
        )
        if clear_message_input:
            self.message_input.clear()
        if clear_recipient_input:
            self.recipient_input.clear()
        self.refresh_from_cache()
