"""Asset-backed, privacy-limited desktop window for one active visiting pet."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QContextMenuEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from ..behavior import PetState
from ..pet_assets import load_pet_asset_bundle


class GuestPetWindow(QWidget):
    """Render a visiting pet without exposing host reminders, messages, or private caches."""

    send_guest_home_requested = Signal(str)
    interaction_requested = Signal(str, str)
    guest_interacted = Signal(str)

    _ACTION_STATES = {
        "greet": PetState.HAPPY,
        "wave": PetState.WAVE,
        "play": PetState.CURIOUS,
        "sit_together": PetState.SIT,
    }
    _ACTION_MESSAGES = {
        "greet": "你好呀，很高兴来串门！",
        "wave": "一起挥挥爪～",
        "play": "来玩一会儿吧！",
        "sit_together": "安静地坐在一起。",
    }

    def __init__(
        self,
        visit_id: str,
        visitor_pet_id: str,
        visitor_pet_name: str,
        visitor_owner_name: str,
        asset_manifest_path: Path | str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.visit_id = visit_id
        self.visitor_pet_id = visitor_pet_id
        self.visitor_pet_name = visitor_pet_name
        self.visitor_owner_name = visitor_owner_name
        self._drag_position = QPoint()
        self._pixmaps: dict[PetState, list[QPixmap]] = {}
        self._state = PetState.IDLE
        self._frame_index = 0
        self._interactions_enabled = True

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(140)
        self._animation_timer.timeout.connect(self._advance_frame)
        self._interaction_timer = QTimer(self)
        self._interaction_timer.setSingleShot(True)
        self._interaction_timer.timeout.connect(self._return_to_idle)
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self.speech_bubble_hide)

        self._setup_flags()
        self._setup_ui()
        if asset_manifest_path is not None:
            self.set_asset_manifest(asset_manifest_path)
        self.speak("来串门啦！")

    @property
    def interactions_enabled(self) -> bool:
        return self._interactions_enabled

    def _setup_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def _setup_ui(self) -> None:
        self.setFixedSize(184, 224)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        self.speech_bubble = QLabel(self)
        self.speech_bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speech_bubble.setWordWrap(True)
        self.speech_bubble.setStyleSheet(
            "QLabel { background: rgba(15,23,42,225); color: white; "
            "border: 1px solid rgba(56,189,248,180); border-radius: 9px; "
            "padding: 5px 8px; font-size: 11px; }"
        )
        layout.addWidget(self.speech_bubble)

        self.avatar_label = QLabel("🐾", self)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setStyleSheet("background: transparent; font-size: 72px;")
        self.avatar_label.setMinimumHeight(144)
        layout.addWidget(self.avatar_label, 1)

        self.name_label = QLabel(self.visitor_pet_name, self)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet(
            "background: rgba(15,23,42,205); color: white; border-radius: 8px; "
            "padding: 3px 7px; font-size: 11px; font-weight: 600;"
        )
        self.name_label.setToolTip(f"主人：{self.visitor_owner_name}")
        layout.addWidget(self.name_label)

    def set_asset_manifest(self, manifest_path: Path | str | None) -> bool:
        """Load a validated package; keep the harmless emoji fallback on failure."""

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

    def set_interactions_enabled(self, enabled: bool) -> None:
        self._interactions_enabled = bool(enabled)
        reason = "" if enabled else "请先切换到本次串门的接待宠物"
        self.avatar_label.setToolTip(reason)

    def request_interaction(self, action: str) -> bool:
        normalized = action.strip().lower()
        if normalized not in self._ACTION_STATES or not self._interactions_enabled:
            return False
        self.interaction_requested.emit(self.visit_id, normalized)
        return True

    def show_interaction(self, action: str) -> None:
        """Animate only after the server confirms the interaction mutation."""

        normalized = action.strip().lower()
        state = self._ACTION_STATES.get(normalized)
        if state is None:
            return
        self.speak(self._ACTION_MESSAGES[normalized])
        self._set_state(state)
        self._interaction_timer.start(2200 if normalized == "sit_together" else 1700)
        self.guest_interacted.emit(normalized)

    def speak(self, text: str) -> None:
        self.speech_bubble.setText(text.strip()[:80] or "🐾")
        self.speech_bubble.show()
        self._bubble_timer.start(2600)

    def speech_bubble_hide(self) -> None:
        self.speech_bubble.hide()

    def _set_state(self, state: PetState) -> None:
        self._state = state if state in self._pixmaps else PetState.IDLE
        self._frame_index = 0
        self._render_frame()

    def _return_to_idle(self) -> None:
        self._set_state(PetState.IDLE)

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
            148,
            148,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.avatar_label.setPixmap(scaled)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.request_interaction("greet")
            event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        actions = (
            ("打招呼", "greet"),
            ("挥挥爪", "wave"),
            ("一起玩", "play"),
            ("并排坐下", "sit_together"),
        )
        for label, action in actions:
            item = QAction(label, menu)
            item.setEnabled(self._interactions_enabled)
            item.triggered.connect(
                lambda _checked=False, action=action: self.request_interaction(action)
            )
            menu.addAction(item)
        menu.addSeparator()
        send_home = QAction("发送访客宠物提前返家", menu)
        send_home.triggered.connect(
            lambda _checked=False: self.send_guest_home_requested.emit(self.visit_id)
        )
        menu.addAction(send_home)
        menu.exec(event.globalPos())

    def closeEvent(self, event: QCloseEvent) -> None:
        self._animation_timer.stop()
        self._interaction_timer.stop()
        self._bubble_timer.stop()
        super().closeEvent(event)
