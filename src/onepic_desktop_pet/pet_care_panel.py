"""紧凑型桌面照料与日常互动状态面板模块。

本模块提供权威状态展示与一键照料请求控制，并在操作成功时
自动记录互动履历至本地 SQLite 数据库。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from .local_store import LocalStateStore


class PetCarePanel(QDialog):
    """显示宠物状态与照料操作控制面板。

    面板不直接在本地篡改 PetProfile 状态，按钮在等待服务器响应时禁用，
    操作成功后更新 UI 并记录日常互动履历。
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

    def __init__(
        self,
        parent=None,
        store: LocalStateStore | None = None,
        pet_id: str = "default_pet",
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.pet_id = pet_id
        self._last_action: tuple[str, str] | None = None

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
                lambda _checked=False, act=action, lbl=label: self._on_action_clicked(act, lbl)
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

    def _on_action_clicked(self, action_type: str, action_name: str) -> None:
        self._last_action = (action_type, action_name)
        self.action_requested.emit(action_type)

    def set_pet(self, pet: PetProfile) -> None:
        self.pet_id = pet.identity.pet_id
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
        if not error and self._last_action and self.store is not None:
            act_type, act_name = self._last_action
            self.store.save_interaction_record(
                pet_id=self.pet_id,
                action_type=act_type,
                action_name=act_name,
                detail=message,
                source="user",
            )
        self._last_action = None
