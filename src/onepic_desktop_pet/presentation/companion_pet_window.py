"""Lightweight second-pet desktop window for explicit two-pet layouts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QContextMenuEvent, QMouseEvent, QMoveEvent, QPixmap
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from ..behavior import PetState
from ..pet_assets import load_pet_asset_bundle


class CompanionPetWindow(QWidget):
    """Render one additional pet without starting a second application stack."""

    activate_requested = Signal(str)
    restore_layout_requested = Signal()
    hide_requested = Signal()
    position_changed = Signal(QPoint)

    def __init__(
        self,
        *,
        pet_id: str,
        pet_name: str,
        asset_manifest_path: Path | str | None,
        display_height: int = 176,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pet_id = pet_id
        self.pet_name = pet_name
        self._drag_offset = QPoint()
        self._pixmaps: dict[PetState, list[QPixmap]] = {}
        self._state = PetState.IDLE
        self._frame_index = 0
        self._display_height = max(120, min(260, int(display_height)))

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle(f"{pet_name} · 并排宠物")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 4, 5, 4)
        layout.setSpacing(2)
        self.avatar_label = QLabel("🐾", self)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setMinimumSize(self._display_height, self._display_height)
        self.avatar_label.setStyleSheet("background: transparent; font-size: 72px;")
        layout.addWidget(self.avatar_label, 1)

        self.name_label = QLabel(pet_name, self)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet(
            "background: rgba(15,23,42,205); color: white; border-radius: 9px; "
            "padding: 4px 8px; font-size: 11px; font-weight: 700;"
        )
        self.name_label.setToolTip("双击切换为当前宠物；拖动可调整并排位置")
        layout.addWidget(self.name_label)

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(180)
        self._animation_timer.timeout.connect(self._advance_frame)
        if asset_manifest_path is not None:
            self.set_asset_manifest(asset_manifest_path)
        self.adjustSize()

    def set_asset_manifest(self, manifest_path: Path | str | None) -> bool:
        if manifest_path is None:
            return False
        try:
            bundle = load_pet_asset_bundle(manifest_path)
        except (OSError, ValueError):
            return False
        self._pixmaps = {state: list(frames) for state, frames in bundle.pixmaps.items()}
        self._state = PetState.IDLE
        self._frame_index = 0
        self._render_frame()
        if not self._animation_timer.isActive():
            self._animation_timer.start()
        return True

    def show_attention(self) -> None:
        self._state = PetState.HAPPY if PetState.HAPPY in self._pixmaps else PetState.IDLE
        self._frame_index = 0
        self._render_frame()
        QTimer.singleShot(1600, self._return_idle)

    def _return_idle(self) -> None:
        self._state = PetState.IDLE
        self._frame_index = 0
        self._render_frame()

    def _advance_frame(self) -> None:
        frames = self._pixmaps.get(self._state)
        if not frames:
            return
        self._frame_index = (self._frame_index + 1) % len(frames)
        self._render_frame()

    def _render_frame(self) -> None:
        frames = self._pixmaps.get(self._state)
        if not frames:
            return
        pixmap = frames[self._frame_index % len(frames)]
        scaled = pixmap.scaled(
            self._display_height,
            self._display_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.avatar_label.setPixmap(scaled)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activate_requested.emit(self.pet_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self.position_changed.emit(QPoint(self.pos()))

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        activate = QAction(f"切换到 {self.pet_name}", menu)
        activate.triggered.connect(lambda: self.activate_requested.emit(self.pet_id))
        menu.addAction(activate)
        restore = QAction("恢复双宠并排布局", menu)
        restore.triggered.connect(self.restore_layout_requested)
        menu.addAction(restore)
        menu.addSeparator()
        hide = QAction("关闭第二只宠物", menu)
        hide.triggered.connect(self.hide_requested)
        menu.addAction(hide)
        menu.exec(event.globalPos())

    def closeEvent(self, event: QCloseEvent) -> None:
        self._animation_timer.stop()
        super().closeEvent(event)
