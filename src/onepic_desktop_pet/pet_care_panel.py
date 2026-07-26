"""紧凑型桌面照料、成长目标与日常互动状态面板。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
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
    """显示权威状态、一键照料、下一成长目标和可回看的成长纪念。"""

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
        self._memory_widgets: list[QFrame] = []

        self.setWindowTitle("宠物状态、成长与照料")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        self.name_label = QLabel("尚未选择宠物")
        self.name_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.growth_label = QLabel("—")
        self.growth_label.setStyleSheet("color: #667085;")
        root.addWidget(self.name_label)
        root.addWidget(self.growth_label)

        self.growth_goal_label = QLabel("正在读取下一步成长目标…")
        self.growth_goal_label.setWordWrap(True)
        self.growth_goal_label.setStyleSheet(
            "background: #fff7ed; border: 1px solid #fed7aa; border-radius: 9px; "
            "padding: 9px 11px; color: #7c4a1d;"
        )
        root.addWidget(self.growth_goal_label)

        growth_grid = QGridLayout()
        growth_grid.addWidget(QLabel("成长等级"), 0, 0)
        self.growth_progress = QProgressBar()
        self.growth_progress.setRange(0, 100)
        self.growth_progress.setFormat("%v / %m")
        growth_grid.addWidget(self.growth_progress, 0, 1)
        growth_grid.addWidget(QLabel("羁绊等级"), 1, 0)
        self.bond_progress = QProgressBar()
        self.bond_progress.setRange(0, 80)
        self.bond_progress.setFormat("%v / %m")
        growth_grid.addWidget(self.bond_progress, 1, 1)
        root.addLayout(growth_grid)

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

        memory_heading = QHBoxLayout()
        memory_heading.addWidget(QLabel("成长纪念册"))
        memory_hint = QLabel("最近 5 条")
        memory_hint.setStyleSheet("color: #98a2b3;")
        memory_heading.addStretch(1)
        memory_heading.addWidget(memory_hint)
        root.addLayout(memory_heading)
        self.memory_layout = QVBoxLayout()
        self.memory_layout.setSpacing(6)
        root.addLayout(self.memory_layout)
        self._render_memories([])

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
        stage_value = getattr(stats.growth_stage, "value", str(stats.growth_stage))
        self.growth_label.setText(
            f"{stage_names.get(stage_value, stage_value)} · "
            f"成长 Lv.{stats.growth_level} · 羁绊 Lv.{stats.bond_level}"
        )
        for field, bar in self.stat_bars.items():
            bar.setValue(int(getattr(stats, field)))

    def set_growth_experience(
        self,
        progress: Mapping[str, object] | None,
        memories: Sequence[Mapping[str, object]] | None,
    ) -> None:
        value = dict(progress or {})
        if value:
            headline = str(value.get("headline") or "继续陪伴即可成长")
            detail = str(value.get("detail") or "不同照料方式都会积累成长经验。")
            estimated = max(0, int(value.get("estimated_actions") or 0))
            estimate_text = f" 按玩耍积累速度约 {estimated} 次。" if estimated else ""
            self.growth_goal_label.setText(f"{headline}。{detail}{estimate_text}")
            growth_target = max(1, int(value.get("growth_level_target") or 100))
            self.growth_progress.setRange(0, growth_target)
            self.growth_progress.setValue(
                max(0, min(growth_target, int(value.get("growth_level_current") or 0)))
            )
            self.growth_progress.setFormat(
                f"%v / %m · 还差 {max(0, int(value.get('growth_exp_remaining') or 0))}"
            )
            bond_target = max(1, int(value.get("bond_level_target") or 80))
            self.bond_progress.setRange(0, bond_target)
            self.bond_progress.setValue(
                max(0, min(bond_target, int(value.get("bond_level_current") or 0)))
            )
            self.bond_progress.setFormat(
                f"%v / %m · 还差 {max(0, int(value.get('bond_exp_remaining') or 0))}"
            )
        else:
            self.growth_goal_label.setText("成长目标暂时不可用，照料功能仍可正常使用。")
            self.growth_progress.setValue(0)
            self.bond_progress.setValue(0)
        self._render_memories(list(memories or []))

    def _render_memories(self, memories: list[Mapping[str, object]]) -> None:
        for widget in self._memory_widgets:
            self.memory_layout.removeWidget(widget)
            widget.deleteLater()
        self._memory_widgets.clear()

        values = memories[:5]
        if not values:
            values = [{
                "icon": "🐾",
                "title": "还没有成长纪念",
                "detail": "升级、羁绊和成长阶段变化会显示在这里。",
                "source_label": "",
            }]
        for memory in values:
            frame = QFrame()
            frame.setStyleSheet(
                "QFrame { background: #f8fafc; border: 1px solid #eaecf0; "
                "border-radius: 8px; padding: 5px; }"
            )
            row = QHBoxLayout(frame)
            row.setContentsMargins(8, 6, 8, 6)
            icon = QLabel(str(memory.get("icon") or "🐾"))
            icon.setFixedWidth(26)
            copy = QVBoxLayout()
            title = QLabel(str(memory.get("title") or "成长纪念"))
            title.setStyleSheet("font-weight: 700; color: #344054;")
            detail = QLabel(str(memory.get("detail") or ""))
            detail.setWordWrap(True)
            detail.setStyleSheet("color: #667085;")
            source = str(memory.get("source_label") or "")
            occurred = memory.get("occurred_at")
            meta_text = " · ".join(part for part in (str(occurred or "")[:10], source) if part)
            meta = QLabel(meta_text)
            meta.setStyleSheet("color: #98a2b3; font-size: 11px;")
            copy.addWidget(title)
            copy.addWidget(detail)
            if meta_text:
                copy.addWidget(meta)
            row.addWidget(icon)
            row.addLayout(copy, 1)
            self.memory_layout.addWidget(frame)
            self._memory_widgets.append(frame)

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
