"""宠物性格对话与互动聊天面板模块。

本模块提供独立的宠物性格聊天面板 GUI，支持玩家与宠物对话、气泡动画反馈、
性格拟人化模拟回答，并完整支持聊天记录与日常互动履历的 SQLite 本地持久化保存，
严格遵守零命令行工具调用的安全边界。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .cute_style import apply_cute_style
from .personality_engine import PersonalityEngine

if TYPE_CHECKING:
    from .local_store import LocalStateStore


class PetChatDialog(QDialog):
    """宠物聊天对话与日常互动记录面板。"""

    # 信号：(文本, 情绪)
    pet_replied = Signal(str, str)

    def __init__(
        self,
        pet_name: str = "小桌宠",
        engine: PersonalityEngine | None = None,
        store: LocalStateStore | None = None,
        pet_id: str = "default_pet",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pet_name = pet_name
        self.engine = engine or PersonalityEngine()
        self.store = store
        self.pet_id = pet_id
        apply_cute_style(self)

        self.setWindowTitle(f"与 {self.pet_name} 聊天对话 (性格演化 & 历史记录)")
        self.resize(540, 500)
        self.setModal(False)

        main_layout = QVBoxLayout(self)

        # 选项卡控件：聊天对话 & 互动履历
        self.tab_widget = QTabWidget(self)
        main_layout.addWidget(self.tab_widget)

        # ================= 1. 聊天对话 TAB =================
        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)

        # 顶部性格契合度卡片
        profile_group = QGroupBox("✨ 自适应性格与契合度档案")
        profile_layout = QHBoxLayout(profile_group)
        self.master_trait_label = QLabel(f"主人标签: {self.engine.master_profile.primary_trait}")
        self.pet_trait_label = QLabel(f"宠物演化: {self.engine.pet_evolution.get_dominant_trait()}")
        self.harmony_label = QLabel(f"契合度: {self.engine.calculate_harmony_index()}%")
        profile_layout.addWidget(self.master_trait_label)
        profile_layout.addWidget(self.pet_trait_label)
        profile_layout.addWidget(self.harmony_label)
        chat_layout.addWidget(profile_group)

        # 消息历史列表
        self.msg_list = QListWidget(self)
        chat_layout.addWidget(self.msg_list, 1)

        # 聊天操作栏 (清空历史按钮)
        chat_tools_layout = QHBoxLayout()
        self.clear_chat_btn = QPushButton("🗑️ 清空聊天记录")
        self.clear_chat_btn.setToolTip("清空当前的聊天历史记录")
        self.clear_chat_btn.clicked.connect(self.clear_chat_history)
        chat_tools_layout.addStretch()
        chat_tools_layout.addWidget(self.clear_chat_btn)
        chat_layout.addLayout(chat_tools_layout)

        # 快捷词
        quick_layout = QHBoxLayout()
        quick_words = ["摸摸你", "今天心情怎么样？", "给你吃好吃的", "辛苦啦！"]
        for word in quick_words:
            btn = QPushButton(word)
            btn.clicked.connect(lambda _, w=word: self.send_user_message(w))
            quick_layout.addWidget(btn)
        chat_layout.addLayout(quick_layout)

        # 输入与发送栏
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(f"和 {self.pet_name} 聊聊天吧...")
        self.input_edit.returnPressed.connect(self._on_send_clicked)

        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._on_send_clicked)

        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.send_btn)
        chat_layout.addLayout(input_layout)

        self.tab_widget.addTab(chat_tab, "💬 聊天对话")

        # ================= 2. 互动履历 TAB =================
        interaction_tab = QWidget()
        interaction_layout = QVBoxLayout(interaction_tab)

        interaction_layout.addWidget(QLabel("📜 近期日常照料与互动履历:"))
        self.interaction_list = QListWidget(self)
        interaction_layout.addWidget(self.interaction_list, 1)

        inter_tools_layout = QHBoxLayout()
        self.refresh_inter_btn = QPushButton("🔄 刷新履历")
        self.refresh_inter_btn.clicked.connect(self.refresh_interaction_history)
        self.clear_inter_btn = QPushButton("🗑️ 清空履历")
        self.clear_inter_btn.clicked.connect(self.clear_interaction_history)
        inter_tools_layout.addWidget(self.refresh_inter_btn)
        inter_tools_layout.addStretch()
        inter_tools_layout.addWidget(self.clear_inter_btn)
        interaction_layout.addLayout(inter_tools_layout)

        self.tab_widget.addTab(interaction_tab, "📜 互动记录")
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # 加载初始/历史消息与互动记录
        self.load_chat_history()
        self.refresh_interaction_history()

    def load_chat_history(self) -> None:
        """从 SQLite 数据库恢复历史聊天记录，若无记录则发送初始欢迎消息。"""
        self.msg_list.clear()
        if self.store is not None:
            history = self.store.list_chat_history(self.pet_id)
            if history:
                for item in history:
                    sender = str(item.get("sender_name") or item.get("sender"))
                    content = str(item.get("content") or "")
                    is_user = item.get("sender") == "user"
                    self._render_chat_bubble(sender, content, is_user=is_user)
                return

        # 若本地无记录，添加初始欢迎消息并持久化
        welcome_text = "主人主人！很高兴能和你聊天~ (๑•̀ㅂ•́)و✧"
        self._add_chat_bubble(self.pet_name, welcome_text, is_user=False, sender_type="pet")

    def refresh_interaction_history(self) -> None:
        """从 SQLite 数据库刷新日常互动履历。"""
        self.interaction_list.clear()
        if self.store is None:
            self.interaction_list.addItem(QListWidgetItem("暂无数据库连接，未启用记录持久化。"))
            return

        records = self.store.list_interaction_records(self.pet_id, limit=100)
        if not records:
            self.interaction_list.addItem(QListWidgetItem("暂无互动履历记录。快去和桌宠互动吧~"))
            return

        for rec in records:
            time_str = rec.get("created_at", "")[:19].replace("T", " ")
            action = rec.get("action_name", rec.get("action_type", ""))
            detail = rec.get("detail", "")
            source = "用户" if rec.get("source") == "user" else rec.get("source", "")
            text = f"[{time_str}] {action}"
            if detail:
                text += f" ({detail})"
            if source:
                text += f" - 触发者: {source}"
            self.interaction_list.addItem(QListWidgetItem(text))

    def clear_chat_history(self) -> None:
        """清空当前聊天历史记录。"""
        self.msg_list.clear()
        if self.store is not None:
            self.store.clear_chat_history(self.pet_id)

    def clear_interaction_history(self) -> None:
        """清空当前互动履历。"""
        self.interaction_list.clear()
        if self.store is not None:
            self.store.clear_interaction_records(self.pet_id)
        self.interaction_list.addItem(QListWidgetItem("已清空所有互动履历。"))

    def send_user_message(self, text: str) -> None:
        """发送用户消息并生成独一无二的性格定制回复，同时进行持久化。"""
        if not text.strip():
            return

        self._add_chat_bubble("你", text, is_user=True, sender_type="user")
        self.input_edit.clear()

        # 生成独一无二拟人回复与性格演化
        reply_text, emotion = self.engine.generate_tailored_reply(text)

        # 刷新顶部档案展示
        self.master_trait_label.setText(f"主人标签: {self.engine.master_profile.primary_trait}")
        self.pet_trait_label.setText(f"宠物演化: {self.engine.pet_evolution.get_dominant_trait()}")
        self.harmony_label.setText(f"契合度: {self.engine.calculate_harmony_index()}%")

        self._add_chat_bubble(self.pet_name, reply_text, is_user=False, sender_type="pet", emotion=emotion)
        self.pet_replied.emit(reply_text, emotion)

    def _on_send_clicked(self) -> None:
        text = self.input_edit.text()
        self.send_user_message(text)

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self.refresh_interaction_history()

    def _add_chat_bubble(
        self,
        sender_name: str,
        content: str,
        is_user: bool,
        sender_type: str = "user",
        emotion: str | None = None,
    ) -> None:
        """渲染气泡并将消息保存至数据库。"""
        self._render_chat_bubble(sender_name, content, is_user=is_user)
        if self.store is not None:
            self.store.save_chat_message(
                pet_id=self.pet_id,
                sender=sender_type,
                sender_name=sender_name,
                content=content,
                emotion=emotion,
            )

    def _render_chat_bubble(self, sender_name: str, content: str, is_user: bool) -> None:
        """纯 UI 视角渲染消息气泡。"""
        item_text = f"[{sender_name}]: {content}"
        item = QListWidgetItem(item_text)
        if is_user:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft)
        self.msg_list.addItem(item)
        self.msg_list.scrollToBottom()

    def _generate_pet_response(self, text: str) -> tuple[str, str]:
        """确定性宠物拟人性格回复模型（无工具调用边界）。"""
        t = text.lower()
        if "摸摸" in t or "好乖" in t:
            return "蹭蹭主人的手~ 感觉心里暖洋洋的！(✿◡‿◡)", "blush"
        elif "吃" in t or "饿" in t:
            return "哇！是有好吃的美食吗？眼睛放光！(๑＞ڡ＜)☆", "happy"
        elif "辛苦" in t or "累" in t:
            return "主人今天也辛苦啦！按按摩放松一下吧~ (⬩˘◡˘⬩)", "happy"
        elif "喝水" in t or "走动" in t:
            return "好的好的！我们一起站起来活动活动身体~ 🍵", "happy"
        else:
            return f"主人说“{text}”，我一直都在你身边陪着你哦！(ฅ´ω`ฅ)", "happy"
