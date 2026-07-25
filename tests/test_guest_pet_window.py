"""桌面访客窗口 GuestPetWindow 与外出标识 AwayIndicator 单元测试。"""

from __future__ import annotations

import sys
import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.presentation.away_indicator import AwayIndicator
from onepic_desktop_pet.presentation.guest_pet_window import GuestPetWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_guest_pet_window_initialization(qapp):
    """验证 GuestPetWindow 初始化与一键送客信号发射。"""
    window = GuestPetWindow(
        visit_id="visit-123",
        visitor_pet_id="pet-456",
        visitor_pet_name="小黄",
        visitor_owner_name="Alice",
    )
    assert window.visit_id == "visit-123"
    assert window.visitor_pet_name == "小黄"
    assert window.visitor_owner_name == "Alice"

    received_visit_id = []
    window.send_guest_home_requested.connect(received_visit_id.append)

    # 模拟触发送客信号
    window.send_guest_home_requested.emit(window.visit_id)
    assert received_visit_id == ["visit-123"]

    window.close()


def test_away_indicator_initialization(qapp):
    """验证 AwayIndicator 外出折叠标识与提前召回信号发射。"""
    indicator = AwayIndicator(
        visit_id="visit-789",
        pet_name="小白",
        host_name="Bob",
        note="去作客半小时",
    )
    assert indicator.visit_id == "visit-789"
    assert indicator.pet_name == "小白"
    assert indicator.host_name == "Bob"

    recalled = []
    indicator.recall_requested.connect(recalled.append)
    indicator.recall_requested.emit(indicator.visit_id)
    assert recalled == ["visit-789"]

    indicator.close()
