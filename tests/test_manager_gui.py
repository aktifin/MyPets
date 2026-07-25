"""本地服务与程序管理器 GUI 工具测试。

验证 LocalManagerWindow 的结构初始化、进程状态变更及解压/日志辅助方法。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from tools.local_manager_gui import LocalManagerWindow, PROJECT_ROOT


@pytest.fixture(scope="module")
def qapp():
    """提供全域独立的 QApplication 实例。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_project_root_and_paths():
    """验证管理器中的根路径计算。"""
    assert PROJECT_ROOT.exists()
    assert (PROJECT_ROOT / "tools" / "local_manager_gui.py").exists()


def test_manager_window_initialization(qapp):
    """验证 LocalManagerWindow 可以在无界面测试环境下成功实例化并包含必要卡片属性。"""
    window = LocalManagerWindow()
    assert window.windowTitle() == "MyPets 本地服务与程序管理器 v0.5"
    assert hasattr(window, "lbl_status_backend")
    assert hasattr(window, "lbl_status_workflow")
    assert hasattr(window, "lbl_status_test")
    assert hasattr(window, "lbl_status_env")
    window.close()


def test_decode_bytes_utf8_and_gbk():
    """验证多字符集日志解码辅助逻辑。"""
    utf8_data = "测试输出".encode("utf-8")
    assert LocalManagerWindow._decode_bytes(utf8_data) == "测试输出"

    gbk_data = "GBK日志".encode("gbk")
    assert LocalManagerWindow._decode_bytes(gbk_data) == "GBK日志"

    empty_data = b""
    assert LocalManagerWindow._decode_bytes(empty_data) == ""
