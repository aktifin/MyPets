"""自适应性格生成与独一无二互动演化引擎单元测试模块。

测试覆盖 MasterPersonalityProfile 主人标签识别、PetPersonalityEvolution
5 维性格积分演化、独一无二性格定制回复生成以及 PetChatDialog 界面联动。
"""

from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from onepic_desktop_pet.personality_engine import PersonalityEngine
from onepic_desktop_pet.pet_chat_dialog import PetChatDialog


def test_master_personality_analysis():
    """测试主人性格关键词提取与标签划分。"""
    engine = PersonalityEngine()

    # 模拟工作狂主人连续输入工作相关文本
    engine.analyze_chat_text("今天又在忙项目代码，开了一下午会")
    engine.analyze_chat_text("加班写项目提交")

    assert engine.master_profile.primary_trait == "专注工作狂型"
    assert engine.master_profile.workaholic_score > 50
    assert engine.pet_evolution.tsundere > 50


def test_caring_master_personality():
    """测试温暖关怀型主人识别与贴心宠物回应。"""
    engine = PersonalityEngine()
    engine.analyze_chat_text("摸摸你，今天辛苦了，记得喝水保重身体哦")

    assert engine.master_profile.primary_trait == "温暖关怀型"
    assert engine.master_profile.caring_score > 50


def test_tailored_reply_generation():
    """测试不同性格组合下的独一无二定制回复。"""
    engine = PersonalityEngine()

    # 1. 模拟工作狂主人 ✖ 傲娇宠物
    engine.master_profile.primary_trait = "专注工作狂型"
    engine.pet_evolution.tsundere = 80
    reply, emotion = engine.generate_tailored_reply("忙工作呢")

    assert "忙" in reply or "累坏" in reply or "傲娇" in reply or "哼" in reply
    assert emotion in ("angry", "blush", "happy")

    # 2. 契合度计算
    harmony = engine.calculate_harmony_index()
    assert 60 <= harmony <= 100


def test_pet_chat_dialog_personality_ui():
    """测试 PetChatDialog 界面性格卡片显示与对话刷新。"""
    engine = PersonalityEngine()
    dialog = PetChatDialog(pet_name="测试宠物", engine=engine)

    assert "主人标签:" in dialog.master_trait_label.text()
    assert "契合度:" in dialog.harmony_label.text()

    # 发送消息
    dialog.send_user_message("哈哈，逗死我了")

    assert "幽默风趣型" in dialog.master_trait_label.text()
    dialog.close()
