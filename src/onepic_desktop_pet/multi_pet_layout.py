"""Device-local controller for a bounded two-pet desktop layout."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

from .config import PetSettings
from .presentation.companion_pet_window import CompanionPetWindow
from .presentation.dual_pet_scene import DualPetSceneCoordinator


class DualPetLayoutController(QObject):
    """Own at most one lightweight companion window and persist both positions."""

    companion_activated = Signal(str)
    companion_hidden = Signal()

    def __init__(
        self,
        *,
        primary_window: QWidget,
        settings: PetSettings,
        save_callback: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.primary_window = primary_window
        self.settings = settings
        self.save_callback = save_callback
        self.companion_window: CompanionPetWindow | None = None
        self._coordinator = DualPetSceneCoordinator(normal_gap=14, interaction_gap=4)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_now)
        self.primary_window.installEventFilter(self)

    @property
    def companion_pet_id(self) -> str:
        return self.companion_window.pet_id if self.companion_window is not None else ""

    @property
    def visible(self) -> bool:
        return self.companion_window is not None and self.companion_window.isVisible()

    def show_companion(
        self,
        *,
        pet_id: str,
        pet_name: str,
        manifest_path: Path | str | None,
        display_height: int,
        use_saved_position: bool = True,
    ) -> CompanionPetWindow:
        if self.companion_window is not None and self.companion_window.pet_id != pet_id:
            self._close_companion()
        if self.companion_window is None:
            companion = CompanionPetWindow(
                pet_id=pet_id,
                pet_name=pet_name,
                asset_manifest_path=manifest_path,
                display_height=max(120, round(display_height * 0.82)),
            )
            companion.activate_requested.connect(self.companion_activated)
            companion.restore_layout_requested.connect(self.restore_layout)
            companion.hide_requested.connect(self.hide_companion)
            companion.position_changed.connect(lambda _point: self._queue_save())
            self.companion_window = companion

        self.settings.multi_pet_layout_enabled = True
        self.settings.multi_pet_companion_pet_id = pet_id
        self.companion_window.show()
        if use_saved_position and self._has_saved_layout():
            self.restore_layout()
        else:
            self.arrange_side_by_side()
        self.companion_window.raise_()
        self._queue_save()
        return self.companion_window

    def arrange_side_by_side(self) -> None:
        companion = self.companion_window
        if companion is None:
            return
        primary = self.primary_window
        primary_point = self._clamp(
            QPoint(primary.x(), primary.y()), primary.size(), reference=primary
        )
        primary.move(primary_point)
        companion_point = self._coordinator.guest_position(primary, companion)
        companion.move(self._clamp(companion_point, companion.size(), reference=primary))
        self.remember_positions()

    def restore_layout(self) -> None:
        companion = self.companion_window
        if companion is None:
            return
        if not self._has_saved_layout():
            self.arrange_side_by_side()
            return
        primary = QPoint(
            int(self.settings.multi_pet_primary_x),
            int(self.settings.multi_pet_primary_y),
        )
        secondary = QPoint(
            int(self.settings.multi_pet_companion_x),
            int(self.settings.multi_pet_companion_y),
        )
        self.primary_window.move(
            self._clamp(primary, self.primary_window.size(), reference=self.primary_window)
        )
        companion.move(self._clamp(secondary, companion.size(), reference=self.primary_window))
        companion.show()
        companion.raise_()
        self._queue_save()

    def hide_companion(self) -> None:
        if self.companion_window is None:
            return
        self.remember_positions()
        self.companion_window.hide()
        self.settings.multi_pet_layout_enabled = False
        self._save_now()
        self.companion_hidden.emit()

    def remember_positions(self) -> None:
        companion = self.companion_window
        if companion is None:
            return
        self.settings.multi_pet_primary_x = self.primary_window.x()
        self.settings.multi_pet_primary_y = self.primary_window.y()
        self.settings.multi_pet_companion_x = companion.x()
        self.settings.multi_pet_companion_y = companion.y()
        self.settings.multi_pet_companion_pet_id = companion.pet_id

    def close(self) -> None:
        self.remember_positions()
        self._save_timer.stop()
        self._close_companion()
        self.primary_window.removeEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.primary_window and event.type() == QEvent.Type.Move and self.visible:
            self._queue_save()
        return super().eventFilter(watched, event)

    def _close_companion(self) -> None:
        companion = self.companion_window
        if companion is None:
            return
        companion.close()
        companion.deleteLater()
        self.companion_window = None

    def _queue_save(self) -> None:
        if self.companion_window is None:
            return
        self.remember_positions()
        self._save_timer.start()

    def _save_now(self) -> None:
        self.remember_positions()
        try:
            self.save_callback()
        except OSError:
            pass

    def _has_saved_layout(self) -> bool:
        return all(
            value is not None
            for value in (
                self.settings.multi_pet_primary_x,
                self.settings.multi_pet_primary_y,
                self.settings.multi_pet_companion_x,
                self.settings.multi_pet_companion_y,
            )
        )

    @staticmethod
    def _clamp(point: QPoint, size: QSize, *, reference: QWidget) -> QPoint:
        screen = QApplication.screenAt(point) or QApplication.screenAt(
            reference.frameGeometry().center()
        ) or QApplication.primaryScreen()
        if screen is None:
            return point
        area = screen.availableGeometry()
        maximum_x = max(area.left(), area.right() - size.width() + 1)
        maximum_y = max(area.top(), area.bottom() - size.height() + 1)
        return QPoint(
            min(max(point.x(), area.left()), maximum_x),
            min(max(point.y(), area.top()), maximum_y),
        )
