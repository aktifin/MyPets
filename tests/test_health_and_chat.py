"""健康提醒与宠物聊天等新功能的单元测试模块。

测试覆盖 InputAnalytics 统计分析、HealthScheduler 提醒触发、
PetChatDialog 对话解析以及 PetCreateDialog 创建流程。
"""

from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

# 确保全局 QApplication 实例存在
app = QApplication.instance() or QApplication([])

from onepic_desktop_pet.health_analytics_dialog import HealthAnalyticsDialog
from onepic_desktop_pet.health_scheduler import HealthScheduler
from onepic_desktop_pet.input_analytics import InputAnalytics
from onepic_desktop_pet.pet_chat_dialog import PetChatDialog
from onepic_desktop_pet.pet_create_dialog import PetCreateDialog


def test_input_analytics_counting():
    """测试 InputAnalytics 按键与点击数统计。"""
    analytics = InputAnalytics()
    analytics.record_keypress()
    analytics.record_keypress()
    analytics.record_mouse_click()

    total_keys, total_clicks = analytics.get_totals()
    assert total_keys == 2
    assert total_clicks == 1
    assert analytics.calculate_fatigue_score() >= 0


def test_health_scheduler_checkin():
    """测试 HealthScheduler 健康打卡机制。"""
    analytics = InputAnalytics()
    scheduler = HealthScheduler(analytics)

    scheduler.checkin("water")
    scheduler.checkin("water")
    scheduler.checkin("stand")

    checkins = scheduler.get_checkin_counts()
    assert checkins["water"] == 2
    assert checkins["stand"] == 1
    assert checkins["rest"] == 0


def test_health_analytics_dialog():
    """测试 HealthAnalyticsDialog 界面数据刷新。"""
    analytics = InputAnalytics()
    scheduler = HealthScheduler(analytics)
    dialog = HealthAnalyticsDialog(analytics, scheduler)

    analytics.record_keypress()
    dialog.refresh_data()
    assert "键盘敲击" in dialog.keys_label.text()
    dialog.close()


def test_pet_chat_dialog():
    """测试 PetChatDialog 聊天与模拟拟人回复。"""
    dialog = PetChatDialog("小测试宠物")
    replies = []
    dialog.pet_replied.connect(lambda text, emotion: replies.append((text, emotion)))

    dialog.send_user_message("摸摸你")

    assert len(replies) == 1
    assert any(k in replies[0][0] for k in ["蹭蹭", "手", "温暖", "主人", "暖和"])
    assert replies[0][1] in ("blush", "happy")
    dialog.close()


def test_pet_create_dialog():
    """测试 PetCreateDialog 初始化与信号。"""
    dialog = PetCreateDialog()
    assert dialog.name_edit.text() == "小宝贝"
    assert dialog.template_combo.count() >= 2
    dialog.close()
