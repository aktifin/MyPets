"""宠物性格对话与互动聊天面板模块。

本模块提供独立的宠物性格聊天面板 GUI，支持玩家与宠物对话、气泡动画反馈
与性格拟人化模拟回答，严格遵守零命令行工具调用的安全边界。
"""

from __future__ import annotations

from typing import List

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
    QVBoxLayout,
    QWidget,
)

from .cute_style import apply_cute_style
from .personality_engine import PersonalityEngine


class PetChatDialog(QDialog):
    """宠物聊天对话框。"""

    # 信号：(文本, 情绪)
    pet_replied = Signal(str, str)

    def __init__(
        self,
        pet_name: str = "小桌宠",
        engine: PersonalityEngine | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pet_name = pet_name
        self.engine = engine or PersonalityEngine()
        apply_cute_style(self)

        self.setWindowTitle(f"与 {self.pet_name} 聊天对话 (性格演化)")
        self.resize(520, 460)
        self.setModal(False)

        root = QVBoxLayout(self)

        # 顶部性格契合度卡片
        profile_group = QGroupBox("✨ 自适应性格与契合度档案")
        profile_layout = QHBoxLayout(profile_group)
        self.master_trait_label = QLabel(f"主人标签: {self.engine.master_profile.primary_trait}")
        self.pet_trait_label = QLabel(f"宠物演化: {self.engine.pet_evolution.get_dominant_trait()}")
        self.harmony_label = QLabel(f"契合度: {self.engine.calculate_harmony_index()}%")
        profile_layout.addWidget(self.master_trait_label)
        profile_layout.addWidget(self.pet_trait_label)
        profile_layout.addWidget(self.harmony_label)
        root.addWidget(profile_group)

        # 消息历史列表
        self.msg_list = QListWidget(self)
        root.addWidget(self.msg_list, 1)

        # 快捷快捷词
        quick_layout = QHBoxLayout()
        quick_words = ["摸摸你", "今天心情怎么样？", "给你吃好吃的", "辛苦啦！"]
        for word in quick_words:
            btn = QPushButton(word)
            btn.clicked.connect(lambda _, w=word: self.send_user_message(w))
            quick_layout.addWidget(btn)
        root.addLayout(quick_layout)

        # 输入与发送栏
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(f"和 {self.pet_name} 聊聊天吧...")
        self.input_edit.returnPressed.connect(self._on_send_clicked)

        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._on_send_clicked)

        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.send_btn)
        root.addLayout(input_layout)

        # 发送初始欢迎消息
        self._add_chat_bubble(f"{self.pet_name}", "主人主人！很高兴能和你聊天~ (๑•̀ㅂ•́)و✧", is_user=False)

    def send_user_message(self, text: str) -> None:
        """发送用户消息并生成独一无二的性格定制回复。"""
        if not text.strip():
            return

        self._add_chat_bubble("你", text, is_user=True)
        self.input_edit.clear()

        # 生成独一无二拟人回复与性格演化
        reply_text, emotion = self.engine.generate_tailored_reply(text)

        # 刷新顶部档案展示
        self.master_trait_label.setText(f"主人标签: {self.engine.master_profile.primary_trait}")
        self.pet_trait_label.setText(f"宠物演化: {self.engine.pet_evolution.get_dominant_trait()}")
        self.harmony_label.setText(f"契合度: {self.engine.calculate_harmony_index()}%")

        self._add_chat_bubble(self.pet_name, reply_text, is_user=False)
        self.pet_replied.emit(reply_text, emotion)

    def _on_send_clicked(self) -> None:
        text = self.input_edit.text()
        self.send_user_message(text)

    def _add_chat_bubble(self, sender: str, content: str, is_user: bool) -> None:
        item_text = f"[{sender}]: {content}"
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
