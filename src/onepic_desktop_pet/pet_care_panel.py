"""Compact, non-modal desktop panel for server-authoritative pet care."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .domain import PetProfile


class PetCarePanel(QDialog):
    """Display cached pet state and emit explicit care requests.

    The panel never mutates PetProfile locally.  Buttons are disabled until the caller
    receives a server response, so visible state cannot get ahead of cloud authority.
    """

    action_requested = Signal(str)

    ACTIONS = (
        ("feed", "投喂"),
        ("play", "玩耍"),
        ("clean", "清洁"),
        ("pet", "摸摸"),
        ("rest", "休息"),
    )
    STATS = (
        ("hunger", "饱食度"),
        ("energy", "精力"),
        ("mood", "心情"),
        ("cleanliness", "清洁度"),
        ("health", "健康"),
        ("boredom", "无聊度"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("宠物状态与照料")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(390)

        root = QVBoxLayout(self)
        self.name_label = QLabel("尚未选择宠物")
        self.name_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.growth_label = QLabel("—")
        self.growth_label.setStyleSheet("color: #667085;")
        root.addWidget(self.name_label)
        root.addWidget(self.growth_label)

        stats_layout = QGridLayout()
        self.stat_bars: dict[str, QProgressBar] = {}
        for row, (field, label) in enumerate(self.STATS):
            stats_layout.addWidget(QLabel(label), row, 0)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFormat("%v / 100")
            stats_layout.addWidget(bar, row, 1)
            self.stat_bars[field] = bar
        root.addLayout(stats_layout)

        actions = QHBoxLayout()
        self.action_buttons: dict[str, QPushButton] = {}
        for action, label in self.ACTIONS:
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, action=action: self.action_requested.emit(action)
            )
            actions.addWidget(button)
            self.action_buttons[action] = button
        root.addLayout(actions)

        self.status_label = QLabel("状态来自本地同步缓存，操作成功后由服务端更新。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #667085;")
        root.addWidget(self.status_label)

        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.hide)
        root.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)

    def set_pet(self, pet: PetProfile) -> None:
        stats = pet.stats
        self.name_label.setText(pet.identity.name)
        stage_names = {
            "newborn": "初生期",
            "child": "幼年期",
            "juvenile": "成长期",
            "adult": "成熟期",
            "bond": "羁绊期",
        }
        self.growth_label.setText(
            f"{stage_names.get(stats.growth_stage.value, stats.growth_stage.value)} · "
            f"等级 {stats.growth_level} · 成长经验 {stats.growth_exp} · "
            f"羁绊 {stats.bond_level} 级"
        )
        for field, bar in self.stat_bars.items():
            bar.setValue(int(getattr(stats, field)))

    def set_busy(self, busy: bool, message: str = "") -> None:
        for button in self.action_buttons.values():
            button.setEnabled(not busy)
        if message:
            self.status_label.setText(message)

    def show_result(self, message: str, *, error: bool = False) -> None:
        self.set_busy(False)
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: #b42318;" if error else "color: #067647;"
        )
