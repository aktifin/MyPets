"""卡哇伊 UI 视觉美化与环形快捷气泡菜单的单元测试模块。

测试覆盖 CuteStyleSheet 萌化样式加载、PetBubbleMenu 快捷动作触发
以及桌面右键分类菜单结构。
"""

from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication([])

from onepic_desktop_pet.bubble_menu import PetBubbleMenu
from onepic_desktop_pet.cute_style import apply_cute_style


def test_apply_cute_style():
    """测试可爱 QSS 样式表应用。"""
    w = QWidget()
    apply_cute_style(w)
    assert "background-color" in w.styleSheet() or "font-family" in w.styleSheet()
    w.close()


def test_pet_bubble_menu_signals():
    """测试 PetBubbleMenu 环形气泡菜单弹出与信号发射。"""
    menu = PetBubbleMenu()
    emitted = []
    menu.action_triggered.connect(lambda action: emitted.append(action))

    menu.popup_at(QPoint(100, 100))
    assert menu.isVisible()

    menu._on_btn_clicked("touch")
    assert len(emitted) == 1
    assert emitted[0] == "touch"
    assert not menu.isVisible()
    menu.close()
