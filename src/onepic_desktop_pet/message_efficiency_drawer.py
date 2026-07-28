"""Searchable message drawer with explicit unread and quick-reply controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .actionable_message_drawer import ActionableMessageDrawer
from .messaging import ConversationRecord, MessageRecord


class QuickReplySettingsDialog(QDialog):
    save_requested = Signal(str, object)
    reset_requested = Signal(str)

    _CATEGORIES = (
        ("direct", "普通私聊"),
        ("friend_pet", "好友宠物"),
        ("visit", "串门留言"),
        ("shared_care", "共同照料"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._preferences: dict[str, list[str]] = {}
        self.setWindowTitle("快捷回复设置")
        self.resize(520, 390)
        root = QVBoxLayout(self)
        intro = QLabel("每行一条，当前顺序就是会话中的展示顺序。点击快捷回复只会填入输入框，确认后再发送。")
        intro.setWordWrap(True)
        root.addWidget(intro)
        form = QFormLayout()
        self.category_combo = QComboBox()
        for value, label in self._CATEGORIES:
            self.category_combo.addItem(label, value)
        self.category_combo.currentIndexChanged.connect(self._render_category)
        form.addRow("回复分类", self.category_combo)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("每行一条快捷回复，保留 1 至 6 条")
        form.addRow("回复内容", self.editor)
        root.addLayout(form, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        actions = QHBoxLayout()
        self.reset_category_button = QPushButton("恢复本类默认")
        self.reset_category_button.clicked.connect(
            lambda: self.reset_requested.emit(str(self.category_combo.currentData()))
        )
        self.reset_all_button = QPushButton("恢复全部默认")
        self.reset_all_button.clicked.connect(lambda: self.reset_requested.emit("all"))
        self.save_button = QPushButton("保存设置")
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.reset_category_button)
        actions.addWidget(self.reset_all_button)
        actions.addStretch(1)
        actions.addWidget(self.save_button)
        root.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

    def set_preferences(self, payload: object) -> None:
        value = payload if isinstance(payload, dict) else {}
        categories = value.get("categories")
        self._preferences = {
            str(key): [str(item) for item in items if str(item).strip()]
            for key, items in categories.items()
            if isinstance(categories, dict) and isinstance(items, list)
        } if isinstance(categories, dict) else {}
        self._render_category()
        self.set_status("设置已加载。")

    def _render_category(self) -> None:
        category = str(self.category_combo.currentData() or "direct")
        self.editor.setPlainText("\n".join(self._preferences.get(category, [])))

    def _save(self) -> None:
        category = str(self.category_combo.currentData() or "direct")
        values = [line.strip() for line in self.editor.toPlainText().splitlines() if line.strip()]
        if not 1 <= len(values) <= 6:
            self.set_status("每类快捷回复需要保留 1 至 6 条。", error=True)
            return
        self.save_requested.emit(category, values)
        self.set_busy(True, "正在保存快捷回复…")

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.category_combo.setEnabled(not busy)
        self.editor.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        self.reset_category_button.setEnabled(not busy)
        self.reset_all_button.setEnabled(not busy)
        if message:
            self.set_status(message)

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #b91c1c;" if error else "color: palette(text);")


class MessageEfficiencyDrawer(ActionableMessageDrawer):
    search_requested = Signal(str)
    window_requested = Signal(str, int)
    unread_requested = Signal(str, int)
    quick_replies_requested = Signal()
    quick_replies_update_requested = Signal(str, object)
    quick_replies_reset_requested = Signal(str)

    def __init__(self, *args, **kwargs) -> None:
        self._search_query = ""
        self._search_results: list[dict[str, object]] = []
        self._anchor_sequence = 0
        self._unread_payload: dict[str, object] = {}
        self._quick_preferences: dict[str, object] = {}
        self._settings_dialog: QuickReplySettingsDialog | None = None
        self._search_timer: QTimer | None = None
        super().__init__(*args, **kwargs)

    def _build_ui(self) -> None:
        super()._build_ui()
        root = self.layout()
        if root is None:
            return
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索联系人、宠物或消息内容")
        self.search_input.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(260)
        self._search_timer.timeout.connect(self._submit_search)
        self.search_input.textChanged.connect(self._search_changed)
        search_row.addWidget(self.search_input, 1)
        self.search_status = QLabel()
        search_row.addWidget(self.search_status)
        root.insertLayout(1, search_row)

        unread_row = QHBoxLayout()
        self.unread_status = QLabel("选择会话后查看未读")
        unread_row.addWidget(self.unread_status, 1)
        self.first_unread_button = QPushButton("第一条未读")
        self.previous_unread_button = QPushButton("上一条未读")
        self.next_unread_button = QPushButton("下一条未读")
        self.read_through_button = QPushButton("读到这里")
        self.first_unread_button.clicked.connect(lambda: self._navigate_unread("first"))
        self.previous_unread_button.clicked.connect(lambda: self._navigate_unread("previous"))
        self.next_unread_button.clicked.connect(lambda: self._navigate_unread("next"))
        self.read_through_button.clicked.connect(self._read_current)
        for button in (
            self.first_unread_button,
            self.previous_unread_button,
            self.next_unread_button,
            self.read_through_button,
        ):
            unread_row.addWidget(button)
        root.insertLayout(max(0, root.count() - 3), unread_row)

        self.quick_settings_button = QPushButton("管理快捷回复")
        self.quick_settings_button.clicked.connect(self._open_quick_settings)
        root.insertWidget(max(0, root.count() - 2), self.quick_settings_button)
        self._render_unread_controls()

    def set_account(self, account_id: str | None, display_name: str = "") -> None:
        super().set_account(account_id, display_name)
        if self.account_id:
            self.quick_replies_requested.emit()
        else:
            self._search_query = ""
            self._search_results = []
            self._unread_payload = {}
            self._anchor_sequence = 0
            self.search_input.clear()
            self._render_unread_controls()

    def _search_changed(self, text: str) -> None:
        normalized = " ".join(text.split())
        self._search_query = normalized
        if self._search_timer is not None:
            self._search_timer.start()
        if not normalized:
            self._search_results = []
            self.search_status.clear()
            self.refresh_from_cache()

    def _submit_search(self) -> None:
        if self._search_query:
            self.search_status.setText("正在搜索…")
            self.search_requested.emit(self._search_query)

    def set_search_results(self, query: str, payload: object) -> None:
        if query != self._search_query:
            return
        value = payload if isinstance(payload, dict) else {}
        items = value.get("items")
        self._search_results = [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        self.search_status.setText(f"{int(value.get('count') or 0)} 个匹配会话")
        self.refresh_from_cache()

    def refresh_from_cache(self) -> None:
        if not hasattr(self, "conversation_list"):
            return
        if not self._search_query:
            super().refresh_from_cache()
            return
        selected = self._selected_conversation_id
        category_value = self.category_combo.currentData()
        category = str(category_value) if category_value else None
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        selected_item: QListWidgetItem | None = None
        for result in self._search_results:
            conversation_data = result.get("conversation")
            if not isinstance(conversation_data, dict):
                continue
            conversation_id = str(conversation_data.get("conversation_id") or "")
            conversation = self.cache.get_conversation(self.account_id, conversation_id)
            if conversation is None or (category and conversation.category != category):
                continue
            snippet = str(result.get("snippet") or "匹配到相关会话")
            item = QListWidgetItem(f"{self._conversation_label(conversation)}\n{snippet}")
            item.setData(Qt.ItemDataRole.UserRole, conversation_id)
            matched = result.get("matched_message")
            sequence = int(matched.get("sequence_number") or 0) if isinstance(matched, dict) else 0
            item.setData(Qt.ItemDataRole.UserRole + 1, sequence)
            item.setToolTip(snippet)
            self.conversation_list.addItem(item)
            if conversation_id == selected:
                selected_item = item
        self.conversation_list.blockSignals(False)
        if selected_item is not None:
            self.conversation_list.setCurrentItem(selected_item)
            self._render_selected()
        elif self.conversation_list.count():
            self.conversation_list.setCurrentRow(0)
        else:
            self._selected_conversation_id = None
            self.conversation_title.setText("没有匹配的会话")
            self.message_list.clear()

    def _select_conversation(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        conversation_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(conversation_id, str) or not conversation_id:
            return
        self._selected_conversation_id = conversation_id
        anchor = item.data(Qt.ItemDataRole.UserRole + 1)
        self._anchor_sequence = int(anchor) if isinstance(anchor, int) else 0
        self._render_selected()
        self.window_requested.emit(conversation_id, self._anchor_sequence)
        self.unread_requested.emit(conversation_id, self._anchor_sequence)
        self.related_detail_requested.emit(conversation_id)

    def _render_selected(self) -> None:
        super()._render_selected()
        self._render_quick_buttons()
        self._highlight_anchor()

    def set_message_window(self, conversation_id: str, payload: object) -> None:
        if conversation_id != self._selected_conversation_id:
            return
        value = payload if isinstance(payload, dict) else {}
        self._anchor_sequence = int(value.get("center_sequence") or self._anchor_sequence or 0)
        self._render_selected()

    def set_unread_navigation(self, conversation_id: str, payload: object) -> None:
        if conversation_id != self._selected_conversation_id:
            return
        self._unread_payload = dict(payload) if isinstance(payload, dict) else {}
        current = self._unread_payload.get("current")
        if isinstance(current, dict):
            self._anchor_sequence = int(current.get("sequence_number") or self._anchor_sequence or 0)
        self._render_unread_controls()
        self._highlight_anchor()

    def _render_unread_controls(self) -> None:
        value = self._unread_payload
        count = int(value.get("unread_count") or 0) if isinstance(value, dict) else 0
        current = value.get("current") if isinstance(value, dict) else None
        sequence = int(current.get("sequence_number") or 0) if isinstance(current, dict) else 0
        self.unread_status.setText(
            f"{count} 条未读" + (f" · 当前第 {sequence} 条" if sequence else "")
            if self._selected_conversation_id
            else "选择会话后查看未读"
        )
        self.first_unread_button.setEnabled(bool(value.get("first")) if isinstance(value, dict) else False)
        self.previous_unread_button.setEnabled(bool(value.get("previous")) if isinstance(value, dict) else False)
        self.next_unread_button.setEnabled(bool(value.get("next")) if isinstance(value, dict) else False)
        self.read_through_button.setEnabled(isinstance(current, dict))

    def _navigate_unread(self, direction: str) -> None:
        if not self._selected_conversation_id:
            return
        key = "first" if direction == "first" else direction
        message = self._unread_payload.get(key)
        if not isinstance(message, dict):
            return
        sequence = int(message.get("sequence_number") or 0)
        if sequence <= 0:
            return
        self._anchor_sequence = sequence
        self.window_requested.emit(self._selected_conversation_id, sequence)
        self.unread_requested.emit(self._selected_conversation_id, sequence)

    def _read_current(self) -> None:
        current = self._unread_payload.get("current")
        if not isinstance(current, dict):
            return
        message_id = str(current.get("message_id") or "")
        if message_id:
            self.read_requested.emit(message_id)
            self.set_status("正在同步已读位置…")

    def _highlight_anchor(self) -> None:
        if not hasattr(self, "message_list"):
            return
        messages = self.cache.list_messages(
            self.account_id,
            self._selected_conversation_id or "",
        ) if self.account_id and self._selected_conversation_id else []
        target_row = -1
        for row, message in enumerate(messages):
            item = self.message_list.item(row)
            if item is None:
                continue
            if message.sequence_number == self._anchor_sequence:
                item.setBackground(QColor("#fff1b8"))
                target_row = row
            else:
                item.setBackground(QColor(Qt.GlobalColor.transparent))
        if target_row >= 0:
            self.message_list.scrollToItem(
                self.message_list.item(target_row),
                self.message_list.ScrollHint.PositionAtCenter,
            )

    def set_quick_reply_preferences(self, payload: object) -> None:
        self._quick_preferences = dict(payload) if isinstance(payload, dict) else {}
        self._render_quick_buttons()
        if self._settings_dialog is not None:
            self._settings_dialog.set_preferences(self._quick_preferences)
            self._settings_dialog.set_busy(False)

    def _category_replies(self, category: str) -> list[str]:
        categories = self._quick_preferences.get("categories")
        if isinstance(categories, dict) and isinstance(categories.get(category), list):
            return [str(item) for item in categories[category]][:6]
        defaults = self._quick_preferences.get("defaults")
        if isinstance(defaults, dict) and isinstance(defaults.get(category), list):
            return [str(item) for item in defaults[category]][:6]
        return []

    def _render_quick_buttons(self) -> None:
        conversation = (
            self.cache.get_conversation(self.account_id, self._selected_conversation_id)
            if self.account_id and self._selected_conversation_id
            else None
        )
        writable = conversation is not None and conversation.kind == "direct"
        replies = self._category_replies(conversation.category if conversation else "direct")
        for index, button in enumerate(self._quick_buttons):
            text = replies[index] if index < len(replies) else ""
            button.setText(text)
            button.setVisible(writable and bool(text))
            button.setEnabled(writable and bool(text))
        self.quick_settings_button.setEnabled(bool(self.account_id))

    def _send_quick_reply(self, text: str) -> None:
        value = text.strip()
        if not value:
            return
        self.message_input.setText(value)
        self.message_input.setFocus()
        self.set_status("快捷回复已填入，请确认后发送。")

    def _open_quick_settings(self) -> None:
        if self._settings_dialog is None:
            dialog = QuickReplySettingsDialog(self)
            dialog.save_requested.connect(self.quick_replies_update_requested)
            dialog.reset_requested.connect(self.quick_replies_reset_requested)
            self._settings_dialog = dialog
        self._settings_dialog.set_preferences(self._quick_preferences)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()
        self.quick_replies_requested.emit()
