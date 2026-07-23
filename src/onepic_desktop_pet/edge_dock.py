"""
PC 桌面宠物左右边缘吸附与半隐藏控制器。

控制器通过事件过滤器附加到现有 PetWindow，不侵入动画和鼠标互动实现。吸附期间
暂停自主跑动；用户拖离边缘后恢复原暂停状态。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QTimer,
)
from PySide6.QtGui import QMouseEvent, QScreen
from PySide6.QtWidgets import QApplication, QWidget

from .config import PetSettings
from .edge_geometry import (
    EdgePlacement,
    EdgeSide,
    calculate_placement,
    choose_edge,
    y_from_offset_ratio,
)


class EdgeDockController(QObject):
    """为任意顶层宠物 QWidget 提供低打扰边缘半隐藏能力。"""

    def __init__(self, window: QWidget, settings: PetSettings) -> None:
        super().__init__(window)
        self.window = window
        self.settings = settings
        self._side: EdgeSide | None = None
        self._screen_name: str | None = None
        self._hidden = False
        self._paused_before_attach: bool | None = None
        self._animation: QPropertyAnimation | None = None

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_to_edge)
        self.window.installEventFilter(self)

    @property
    def side(self) -> EdgeSide | None:
        return self._side

    @property
    def attached(self) -> bool:
        return self._side is not None

    @property
    def hidden(self) -> bool:
        return self._hidden

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is not self.window or not self.settings.edge_dock_enabled:
            return super().eventFilter(watched, event)

        event_type = event.type()
        if event_type == QEvent.Type.Enter and self.attached:
            self.reveal_from_edge()
        elif event_type == QEvent.Type.Leave and self.attached:
            self.schedule_hide()
        elif event_type == QEvent.Type.MouseButtonPress and self.attached:
            # 先完整展开，再由 PetWindow 计算拖拽偏移，避免隐藏位置造成跳跃。
            self.reveal_from_edge(immediate=True)
        elif event_type == QEvent.Type.MouseMove and self.attached:
            if isinstance(event, QMouseEvent) and event.buttons():
                self.detach(keep_position=True)
        elif event_type == QEvent.Type.MouseButtonRelease:
            # 目标窗口先完成自己的 release 逻辑，再判断是否靠近边缘。
            QTimer.singleShot(0, self.attach_to_nearest_edge)
        return super().eventFilter(watched, event)

    def restore(self) -> None:
        """应用启动后恢复上次屏幕、边缘和纵向位置。"""

        if not self.settings.edge_dock_enabled or not self.settings.edge_side:
            return
        try:
            side = EdgeSide(self.settings.edge_side)
        except ValueError:
            self.settings.edge_side = None
            return

        screen = self._screen_by_name(self.settings.edge_screen_name)
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        ratio = self.settings.edge_offset_ratio
        y = y_from_offset_ratio(
            area.top(),
            area.bottom(),
            self.window.height(),
            0.5 if ratio is None else ratio,
        )
        self._set_attached_state(side, screen)
        placement = self._placement(screen, y)
        self.window.move(placement.expanded_x, placement.y)
        self._store_placement(placement)
        self.schedule_hide()

    def attach(self, side: EdgeSide) -> None:
        """将宠物吸附到当前屏幕指定边缘。"""

        screen = self._current_screen()
        if screen is None:
            return
        self._set_attached_state(side, screen)
        placement = self._placement(screen, self.window.y())
        self._store_placement(placement)
        self._animate_to(
            QPoint(placement.expanded_x, placement.y),
            self.settings.edge_animation_ms,
            self.schedule_hide,
        )

    def attach_to_nearest_edge(self) -> None:
        """拖拽释放后在阈值内自动吸附，否则保持自由状态。"""

        if not self.settings.edge_dock_enabled or self.attached:
            return
        screen = self._current_screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        side = choose_edge(
            self.window.x(),
            self.window.x() + self.window.width() - 1,
            area.left(),
            area.right(),
            self.settings.edge_snap_distance,
        )
        if side is not None:
            self.attach(side)

    def schedule_hide(self) -> None:
        if not self.attached:
            return
        self._hide_timer.start(self.settings.edge_hide_delay_ms)

    def hide_to_edge(self) -> None:
        """滑入边缘，只保留配置比例的可见区域。"""

        if not self.attached:
            return
        screen = self._attached_screen()
        if screen is None:
            return
        placement = self._placement(screen, self.window.y())
        self._store_placement(placement)
        self._hidden = True
        self._animate_to(
            QPoint(placement.hidden_x, placement.y),
            self.settings.edge_animation_ms,
        )

    def reveal_from_edge(self, immediate: bool = False) -> None:
        """从边缘滑出；不激活窗口，也不抢占键盘焦点。"""

        if not self.attached:
            return
        self._hide_timer.stop()
        screen = self._attached_screen()
        if screen is None:
            return
        placement = self._placement(screen, self.window.y())
        self._store_placement(placement)
        self._hidden = False
        self._animate_to(
            QPoint(placement.expanded_x, placement.y),
            0 if immediate else self.settings.edge_animation_ms,
        )

    def detach(self, keep_position: bool = False) -> None:
        """解除边缘吸附并恢复吸附前的跑动设置。"""

        if not self.attached:
            return
        self._hide_timer.stop()
        screen = self._attached_screen()
        if not keep_position and screen is not None:
            placement = self._placement(screen, self.window.y())
            self._animate_to(
                QPoint(placement.expanded_x, placement.y),
                self.settings.edge_animation_ms,
            )
        elif self._animation is not None:
            self._animation.stop()

        self._side = None
        self._screen_name = None
        self._hidden = False
        self.settings.edge_side = None
        self.settings.edge_screen_name = None
        self.settings.edge_offset_ratio = None
        self._restore_pause_state()

    def persistence_position(self) -> QPoint:
        """返回可用于启动回退的完整可见位置，而不是屏幕外隐藏坐标。"""

        if not self.attached:
            return self.window.pos()
        screen = self._attached_screen()
        if screen is None:
            return self.window.pos()
        placement = self._placement(screen, self.window.y())
        self._store_placement(placement)
        return QPoint(placement.expanded_x, placement.y)

    def _set_attached_state(self, side: EdgeSide, screen: QScreen) -> None:
        if self._paused_before_attach is None:
            self._paused_before_attach = bool(getattr(self.window, "paused", False))
        set_paused = getattr(self.window, "set_paused", None)
        if callable(set_paused) and not getattr(self.window, "paused", False):
            set_paused(True)
        self._side = side
        self._screen_name = screen.name()
        self.settings.edge_side = side.value
        self.settings.edge_screen_name = screen.name()

    def _restore_pause_state(self) -> None:
        previous = self._paused_before_attach
        self._paused_before_attach = None
        set_paused = getattr(self.window, "set_paused", None)
        if previous is not None and callable(set_paused):
            set_paused(previous)

    def _current_screen(self) -> QScreen | None:
        screen = QApplication.screenAt(self.window.frameGeometry().center())
        if screen is not None:
            return screen
        handle = self.window.windowHandle()
        if handle is not None and handle.screen() is not None:
            return handle.screen()
        return QApplication.primaryScreen()

    def _attached_screen(self) -> QScreen | None:
        return self._screen_by_name(self._screen_name) or self._current_screen()

    @staticmethod
    def _screen_by_name(name: str | None) -> QScreen | None:
        if not name:
            return None
        return next((screen for screen in QApplication.screens() if screen.name() == name), None)

    def _placement(self, screen: QScreen, current_y: int) -> EdgePlacement:
        if self._side is None:
            raise RuntimeError("宠物尚未吸附到边缘")
        area = screen.availableGeometry()
        return calculate_placement(
            self._side,
            area_left=area.left(),
            area_top=area.top(),
            area_right=area.right(),
            area_bottom=area.bottom(),
            window_width=self.window.width(),
            window_height=self.window.height(),
            current_y=current_y,
            visible_ratio=self.settings.edge_visible_ratio,
        )

    def _store_placement(self, placement: EdgePlacement) -> None:
        self.settings.edge_side = placement.side.value
        self.settings.edge_screen_name = self._screen_name
        self.settings.edge_offset_ratio = placement.offset_ratio

    def _animate_to(
        self,
        target: QPoint,
        duration_ms: int,
        finished: Callable[[], None] | None = None,
    ) -> None:
        if self._animation is not None:
            self._animation.stop()
        if duration_ms <= 0:
            self.window.move(target)
            if finished is not None:
                finished()
            return
        animation = QPropertyAnimation(self.window, b"pos", self)
        animation.setDuration(max(1, int(duration_ms)))
        animation.setStartValue(self.window.pos())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        if finished is not None:
            animation.finished.connect(finished)
        self._animation = animation
        animation.start()
