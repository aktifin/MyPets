"""
本模块管理桌面宠物应用生命周期、系统托盘菜单和设备级状态保存。

职责范围：
- 创建或复用 QApplication；
- 在创建应用前启用适合不同显示器缩放比例的高 DPI 舍入策略；
- 创建 PetWindow、边缘吸附控制器和 QSystemTrayIcon；
- 连接显示、隐藏、暂停跑动、互动、边缘吸附和退出动作；
- 退出前保存完整可见位置、显示尺寸和边缘吸附状态；
- 为自动验证提供定时退出的 smoke-test 参数。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .config import PetSettings, load_settings, save_settings
from .edge_dock import EdgeDockController
from .edge_geometry import EdgeSide
from .resources import resource_path
from .window import PetWindow


class DesktopPetApplication:
    """封装窗口、托盘、边缘模式与持久化状态的桌面宠物应用。"""

    def __init__(self, settings: PetSettings | None = None) -> None:
        if QApplication.instance() is None:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.qt_app.setApplicationName("OnePic Desktop Pet")
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.settings = settings or load_settings()
        self.window = PetWindow(self.settings)
        self.edge_dock = EdgeDockController(self.window, self.settings)
        self.window.quit_requested.connect(self.quit)
        self.tray = self._create_tray()

    def _create_tray(self) -> QSystemTrayIcon:
        """创建系统托盘图标及其操作菜单。"""

        icon = QIcon(str(resource_path("assets/icons/pet.png")))
        tray = QSystemTrayIcon(icon, self.qt_app)
        tray.setToolTip("OnePic Desktop Pet")
        menu = QMenu()

        show_action = QAction("显示宠物", menu)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)

        interact_action = QAction("和她打招呼", menu)
        interact_action.triggered.connect(self.window.trigger_interaction)
        menu.addAction(interact_action)

        selfie_action = QAction("自拍一下", menu)
        selfie_action.triggered.connect(self.window.trigger_selfie)
        menu.addAction(selfie_action)

        pause_action = QAction("暂停/恢复跑动", menu)
        pause_action.triggered.connect(
            lambda: self.window.set_paused(not self.window.paused)
        )
        menu.addAction(pause_action)

        edge_menu = menu.addMenu("边缘吸附")
        attach_left = QAction("吸附到左侧", edge_menu)
        attach_left.triggered.connect(
            lambda _checked=False: self.edge_dock.attach(EdgeSide.LEFT)
        )
        edge_menu.addAction(attach_left)

        attach_right = QAction("吸附到右侧", edge_menu)
        attach_right.triggered.connect(
            lambda _checked=False: self.edge_dock.attach(EdgeSide.RIGHT)
        )
        edge_menu.addAction(attach_right)

        reveal_action = QAction("暂时展开", edge_menu)
        reveal_action.triggered.connect(self.edge_dock.reveal_from_edge)
        edge_menu.addAction(reveal_action)

        detach_action = QAction("解除吸附", edge_menu)
        detach_action.triggered.connect(self.edge_dock.detach)
        edge_menu.addAction(detach_action)

        hide_action = QAction("隐藏宠物", menu)
        hide_action.triggered.connect(self.window.hide)
        menu.addAction(hide_action)
        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        self.tray_menu = menu
        tray.activated.connect(self._tray_activated)
        return tray

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """单击或双击托盘图标时显示并展开宠物。"""

        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def show_window(self) -> None:
        """显示宠物；已吸附时先从边缘展开。"""

        self.window.show()
        if self.edge_dock.attached:
            self.edge_dock.reveal_from_edge()
        self.window.raise_()
        self.window.activateWindow()

    def start(self, smoke_test_ms: int | None = None) -> int:
        """显示应用并进入事件循环；可选定时退出用于自动验证。"""

        self.window.place_at_start()
        self.show_window()
        QTimer.singleShot(0, self.edge_dock.restore)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        if smoke_test_ms is not None:
            QTimer.singleShot(max(1, smoke_test_ms), self.quit)
        return self.qt_app.exec()

    def quit(self) -> None:
        """保存窗口及边缘状态、隐藏托盘并退出应用。"""

        position = self.edge_dock.persistence_position()
        self.settings.start_x = position.x()
        self.settings.start_y = position.y()
        try:
            save_settings(self.settings)
        finally:
            self.tray.hide()
            self.window.close()
            self.qt_app.quit()


def run(smoke_test_ms: int | None = None) -> int:
    """创建并运行桌面宠物应用。"""

    return DesktopPetApplication().start(smoke_test_ms=smoke_test_ms)
