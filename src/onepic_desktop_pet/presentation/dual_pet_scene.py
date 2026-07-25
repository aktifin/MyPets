"""Deterministic desktop placement for one host pet and one active visiting pet."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


class DualPetSceneCoordinator:
    """Keep the guest beside the host while respecting the active screen work area."""

    def __init__(self, normal_gap: int = 14, interaction_gap: int = 4) -> None:
        self.normal_gap = max(0, int(normal_gap))
        self.interaction_gap = max(0, int(interaction_gap))

    @staticmethod
    def _available_geometry(host: QWidget) -> QRect:
        screen = host.screen() or QGuiApplication.screenAt(host.frameGeometry().center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)

    def guest_position(
        self,
        host: QWidget,
        guest: QWidget,
        *,
        close_interaction: bool = False,
    ) -> QPoint:
        available = self._available_geometry(host)
        host_rect = host.frameGeometry()
        gap = self.interaction_gap if close_interaction else self.normal_gap

        right_x = host_rect.right() + 1 + gap
        left_x = host_rect.left() - guest.width() - gap
        if right_x + guest.width() <= available.right() + 1:
            x = right_x
        elif left_x >= available.left():
            x = left_x
        else:
            x = min(
                max(host_rect.center().x() - guest.width() // 2, available.left()),
                available.right() - guest.width() + 1,
            )

        y = host_rect.bottom() - guest.height() + 1
        y = min(max(y, available.top()), available.bottom() - guest.height() + 1)
        return QPoint(x, y)

    def place_guest(
        self,
        host: QWidget,
        guest: QWidget,
        *,
        close_interaction: bool = False,
    ) -> QPoint:
        point = self.guest_position(host, guest, close_interaction=close_interaction)
        guest.move(point)
        return point

    def place_indicator(self, host: QWidget, indicator: QWidget) -> QPoint:
        available = self._available_geometry(host)
        host_rect = host.frameGeometry()
        x = min(
            max(host_rect.center().x() - indicator.width() // 2, available.left()),
            available.right() - indicator.width() + 1,
        )
        y = min(
            max(host_rect.bottom() - indicator.height() + 1, available.top()),
            available.bottom() - indicator.height() + 1,
        )
        point = QPoint(x, y)
        indicator.move(point)
        return point
