"""Single-window Windows party scene; it never creates additional desktop pet windows."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

DESKTOP_PARTY_WINDOW_LIMIT = 2

_STATUS_LABELS = {
    "open": "等待好友",
    "active": "欢乐进行中",
    "completed": "温馨结束",
    "cancelled": "本次已取消",
}
_MEMBER_LABELS = {
    "invited": "等待回应",
    "accepted": "已经准备好",
    "declined": "这次不参加",
    "joined": "正在聚会",
    "left": "已经回家",
    "completed": "聚会完成",
    "expired": "邀请已结束",
}
_INTERACTION_LABELS = {
    "greet_circle": "围圈打招呼",
    "play_together": "一起玩耍",
    "group_photo": "留下合影",
    "rest_together": "一起休息",
}
_ACTIVITY_PRESENTATION = {
    "greet_circle": ("👋", "大家正在互相打招呼", "开心打招呼"),
    "play_together": ("🧶", "它们正在一起玩耍", "一起玩耍"),
    "group_photo": ("📷", "宠物们刚刚留下了合影", "等待合影"),
    "rest_together": ("☁️", "它们正在安静地一起休息", "一起休息"),
    "waiting": ("🐾", "等待好友宠物到齐", "等待开始"),
    "free_play": ("✨", "宠物们正在自由玩耍", "自由玩耍"),
    "ended": ("🏠", "宠物们已经安全回家", "已经回家"),
}


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _pet_icon(pet: Mapping[str, object]) -> str:
    template = str(pet.get("template_id") or "").lower()
    if "dog" in template:
        return "🐶"
    if "rabbit" in template or "bunny" in template:
        return "🐰"
    if "bird" in template:
        return "🐦"
    return "🐱"


class PartyDialog(QDialog):
    refresh_requested = Signal()
    detail_requested = Signal(str)
    create_requested = Signal(str, str, int, int)
    invite_requested = Signal(str, str)
    accept_requested = Signal(str, str)
    action_requested = Signal(str, str)
    interaction_requested = Signal(str, str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("宠物小聚场景")
        self.setModal(False)
        self.resize(1080, 720)
        self.setMinimumSize(860, 600)
        self.setObjectName("partyDialog")
        self._parties: dict[str, dict[str, object]] = {}
        self._current_party_id = ""
        self._current_pet_id = ""
        self._current_pet_name = ""
        self._current_pet_available = False
        self.member_cards: list[QFrame] = []

        self.setStyleSheet(
            """
            QDialog#partyDialog { background: #f7f8fa; }
            QFrame#partyHero, QFrame#partyStage, QFrame#partyCreateBar {
                background: white;
                border: 1px solid #e4e7ec;
                border-radius: 16px;
            }
            QFrame#partyStage {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #fff9ef, stop:1 #f1f7ff);
            }
            QFrame[memberCard="true"] {
                background: rgba(255, 255, 255, 230);
                border: 1px solid #dfe4ea;
                border-radius: 14px;
            }
            QLabel[statusPill="true"] {
                background: #ecfdf3;
                color: #067647;
                border-radius: 10px;
                padding: 4px 9px;
                font-weight: 700;
            }
            QLabel[activityPill="true"] {
                background: #f2f4f7;
                color: #475467;
                border-radius: 9px;
                padding: 3px 8px;
            }
            QListWidget {
                background: white;
                border: 1px solid #e4e7ec;
                border-radius: 12px;
                padding: 4px;
            }
            QListWidget::item {
                border-radius: 8px;
                padding: 8px;
                margin: 2px;
            }
            QListWidget::item:selected { background: #eef4ff; color: #1849a9; }
            QPushButton { min-height: 30px; padding: 3px 10px; }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("partyHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        copy = QVBoxLayout()
        title = QLabel("宠物小聚场景")
        title.setStyleSheet("font-size: 21px; font-weight: 800; color: #344054;")
        self.summary_label = QLabel(
            "好友宠物集中在一个轻量场景中互动，桌面宠物仍保持简洁展示。"
        )
        self.summary_label.setStyleSheet("color: #667085;")
        self.summary_label.setWordWrap(True)
        copy.addWidget(title)
        copy.addWidget(self.summary_label)
        hero_layout.addLayout(copy, 1)
        self.refresh_button = QPushButton("刷新动态")
        self.refresh_button.clicked.connect(self.refresh_requested)
        hero_layout.addWidget(self.refresh_button)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.hide)
        hero_layout.addWidget(close_button)
        root.addWidget(hero)

        create_bar = QFrame()
        create_bar.setObjectName("partyCreateBar")
        create_row = QHBoxLayout(create_bar)
        create_row.setContentsMargins(12, 10, 12, 10)
        self.current_pet_label = QLabel("当前宠物：未选择")
        self.current_pet_label.setMinimumWidth(190)
        create_row.addWidget(self.current_pet_label)
        self.create_title = QLineEdit("宠物小聚会")
        self.create_title.setMaxLength(80)
        self.create_title.setPlaceholderText("给聚会起个名字")
        create_row.addWidget(self.create_title, 1)
        self.create_count = QComboBox()
        self.create_count.addItem("2 只宠物", 2)
        self.create_count.addItem("3 只宠物", 3)
        self.create_count.addItem("4 只宠物", 4)
        self.create_count.setCurrentIndex(2)
        create_row.addWidget(self.create_count)
        self.create_duration = QComboBox()
        for minutes in (30, 60, 120, 180):
            self.create_duration.addItem(f"{minutes} 分钟", minutes)
        self.create_duration.setCurrentIndex(1)
        create_row.addWidget(self.create_duration)
        self.create_button = QPushButton("发起新聚会")
        self.create_button.setEnabled(False)
        self.create_button.clicked.connect(self._create)
        create_row.addWidget(self.create_button)
        root.addWidget(create_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_title = QLabel("我的邀请与聚会")
        left_title.setStyleSheet("font-weight: 700; color: #344054;")
        left_layout.addWidget(left_title)
        self.party_list = QListWidget()
        self.party_list.currentItemChanged.connect(self._select_party)
        left_layout.addWidget(self.party_list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        scene_header = QHBoxLayout()
        scene_copy = QVBoxLayout()
        self.party_title_label = QLabel("选择一场聚会")
        self.party_title_label.setStyleSheet("font-size: 19px; font-weight: 750; color: #344054;")
        scene_copy.addWidget(self.party_title_label)
        self.party_meta_label = QLabel("聚会成员会以卡片方式出现在同一个场景中。")
        self.party_meta_label.setStyleSheet("color: #667085;")
        self.party_meta_label.setWordWrap(True)
        scene_copy.addWidget(self.party_meta_label)
        scene_header.addLayout(scene_copy, 1)
        self.party_status_label = QLabel("等待选择")
        self.party_status_label.setProperty("statusPill", True)
        scene_header.addWidget(self.party_status_label, 0, Qt.AlignmentFlag.AlignTop)
        right_layout.addLayout(scene_header)

        self.scene_frame = QFrame()
        self.scene_frame.setObjectName("partyStage")
        scene_layout = QVBoxLayout(self.scene_frame)
        scene_layout.setContentsMargins(16, 14, 16, 14)
        scene_layout.setSpacing(10)
        self.activity_label = QLabel("🐾 选择一场聚会，看看宠物们在做什么")
        self.activity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.activity_label.setWordWrap(True)
        self.activity_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #344054;")
        scene_layout.addWidget(self.activity_label)

        self.member_scroll = QScrollArea()
        self.member_scroll.setWidgetResizable(True)
        self.member_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.member_scroll.setStyleSheet("background: transparent;")
        self.member_container = QWidget()
        self.member_container.setStyleSheet("background: transparent;")
        self.member_grid = QGridLayout(self.member_container)
        self.member_grid.setContentsMargins(0, 0, 0, 0)
        self.member_grid.setHorizontalSpacing(10)
        self.member_grid.setVerticalSpacing(10)
        self.member_scroll.setWidget(self.member_container)
        scene_layout.addWidget(self.member_scroll, 1)
        self.empty_scene_label = QLabel("还没有聚会成员。发起聚会并邀请好友一起玩。")
        self.empty_scene_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_scene_label.setStyleSheet("color: #667085; padding: 24px;")
        self.member_grid.addWidget(self.empty_scene_label, 0, 0, 1, 2)
        right_layout.addWidget(self.scene_frame, 3)

        invite_form = QFormLayout()
        invite_row = QHBoxLayout()
        self.invite_username = QLineEdit()
        self.invite_username.setPlaceholderText("输入好友的精确用户名")
        self.invite_username.setMaxLength(64)
        invite_row.addWidget(self.invite_username, 1)
        self.invite_button = QPushButton("发送邀请")
        self.invite_button.clicked.connect(self._invite)
        invite_row.addWidget(self.invite_button)
        invite_form.addRow("邀请好友", invite_row)
        right_layout.addLayout(invite_form)

        action_row = QHBoxLayout()
        self.accept_button = QPushButton("带当前宠物参加")
        self.accept_button.clicked.connect(lambda: self._action("accept"))
        action_row.addWidget(self.accept_button)
        self.decline_button = QPushButton("这次不参加")
        self.decline_button.clicked.connect(lambda: self._action("decline"))
        action_row.addWidget(self.decline_button)
        self.start_button = QPushButton("大家到齐，开始")
        self.start_button.clicked.connect(lambda: self._action("start"))
        action_row.addWidget(self.start_button)
        self.leave_button = QPushButton("带宠物回家")
        self.leave_button.clicked.connect(lambda: self._action("leave"))
        action_row.addWidget(self.leave_button)
        self.cancel_button = QPushButton("取消本次聚会")
        self.cancel_button.clicked.connect(lambda: self._action("cancel"))
        action_row.addWidget(self.cancel_button)
        self.end_button = QPushButton("温馨结束")
        self.end_button.clicked.connect(lambda: self._action("end"))
        action_row.addWidget(self.end_button)
        right_layout.addLayout(action_row)

        interaction_row = QHBoxLayout()
        self.interaction_buttons: dict[str, QPushButton] = {}
        for action, label in _INTERACTION_LABELS.items():
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=action: self._interact(value)
            )
            self.interaction_buttons[action] = button
            interaction_row.addWidget(button)
        right_layout.addLayout(interaction_row)

        timeline_title = QLabel("聚会故事")
        timeline_title.setStyleSheet("font-weight: 700; color: #344054;")
        right_layout.addWidget(timeline_title)
        self.timeline_list = QListWidget()
        self.timeline_list.setMaximumHeight(170)
        right_layout.addWidget(self.timeline_list, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        self.status_label = QLabel("聚会只记录社交互动，不改变宠物归属或共同照料关系。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #667085;")
        root.addWidget(self.status_label)
        self._update_actions(None)

    def set_current_pet(
        self,
        pet_id: str | None,
        name: str = "",
        *,
        available: bool = False,
    ) -> None:
        self._current_pet_id = str(pet_id or "")
        self._current_pet_name = name
        self._current_pet_available = bool(self._current_pet_id and available)
        suffix = "可以参加" if self._current_pet_available else "当前不在家"
        self.current_pet_label.setText(
            f"当前宠物：{name or '未选择'} · {suffix}"
        )
        self.create_button.setEnabled(self._current_pet_available)
        self._update_actions(self._current_party())

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        if busy:
            self.set_status("正在读取聚会动态…")

    def set_snapshot(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            self.set_status("聚会列表响应无效", error=True)
            return
        selected_id = self._current_party_id
        self._parties.clear()
        self.party_list.clear()
        categories = (
            ("等我回应", payload.get("invitations")),
            ("等待开始", payload.get("open")),
            ("正在玩耍", payload.get("active")),
            ("聚会回忆", payload.get("history")),
        )
        for category, raw_values in categories:
            values = raw_values if isinstance(raw_values, list) else []
            for raw in values:
                if not isinstance(raw, Mapping):
                    continue
                party = dict(raw)
                party_id = str(party.get("party_id") or "")
                if not party_id or party_id in self._parties:
                    continue
                self._parties[party_id] = party
                accepted = int(party.get("accepted_count") or 0)
                maximum = int(party.get("max_members") or 0)
                item = QListWidgetItem(
                    f"{category}\n{party.get('title') or '宠物小聚会'} · {accepted}/{maximum} 只已确认"
                )
                item.setData(Qt.ItemDataRole.UserRole, party_id)
                item.setToolTip(_STATUS_LABELS.get(str(party.get("status") or ""), "宠物聚会"))
                self.party_list.addItem(item)
                if party_id == selected_id:
                    self.party_list.setCurrentItem(item)
        if not self._parties:
            self._current_party_id = ""
            self.party_title_label.setText("还没有宠物聚会")
            self.party_meta_label.setText("使用上方当前宠物发起聚会，再邀请好友一起玩。")
            self.party_status_label.setText("等待发起")
            self.activity_label.setText("🎈 发起第一场聚会，宠物们会在这里相聚")
            self._render_members([], "waiting")
            self.timeline_list.clear()
            self.timeline_list.addItem("聚会开始后，邀请、互动和返家故事会显示在这里。")
            self._update_actions(None)
        elif self.party_list.currentRow() < 0:
            self.party_list.setCurrentRow(0)
        self.set_busy(False)
        self.set_status(f"已同步 {len(self._parties)} 场聚会，全部成员共用一个场景。")

    def set_detail(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            self.set_status("聚会详情响应无效", error=True)
            return
        party = dict(payload)
        party_id = str(party.get("party_id") or "")
        if not party_id:
            self.set_status("聚会详情缺少编号", error=True)
            return
        self._parties[party_id] = party
        self._current_party_id = party_id
        self._render_party(party)
        self.set_status("聚会场景与故事已刷新。")

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #b42318;" if error else "color: #067647;")

    def _current_party(self) -> dict[str, object] | None:
        return self._parties.get(self._current_party_id)

    def _select_party(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        party_id = str(current.data(Qt.ItemDataRole.UserRole) or "") if current else ""
        self._current_party_id = party_id
        party = self._parties.get(party_id)
        if party is not None:
            self._render_party(party)
            self.detail_requested.emit(party_id)
        else:
            self._update_actions(None)

    def _activity_key(self, party: Mapping[str, object]) -> str:
        timeline = party.get("timeline") if isinstance(party.get("timeline"), list) else []
        for raw in reversed(timeline):
            if not isinstance(raw, Mapping):
                continue
            action = str(raw.get("action") or "")
            if str(raw.get("kind") or "") == "interaction" and action in _ACTIVITY_PRESENTATION:
                return action
        status = str(party.get("status") or "")
        if status == "open":
            return "waiting"
        if status == "active":
            return "free_play"
        return "ended"

    def _render_party(self, party: dict[str, object]) -> None:
        self.party_title_label.setText(str(party.get("title") or "宠物小聚会"))
        status = str(party.get("status") or "")
        joined = int(party.get("joined_count") or 0)
        accepted = int(party.get("accepted_count") or 0)
        maximum = int(party.get("max_members") or 0)
        self.party_status_label.setText(_STATUS_LABELS.get(status, "宠物聚会"))
        if status == "active":
            description = f"{joined} 只宠物正在同一个场景中玩耍"
        elif status == "open" and accepted >= 2:
            description = "好友宠物已经准备好，可以开始聚会"
        elif status == "open":
            description = "正在等待好友带宠物加入"
        else:
            description = "宠物们已经安全回家"
        self.party_meta_label.setText(
            f"{description} · 已确认 {accepted}/{maximum} 只 · 每位好友携带一只宠物"
        )
        raw_members = party.get("members")
        members = raw_members if isinstance(raw_members, list) else []
        activity_key = self._activity_key(party)
        icon, title, _member_activity = _ACTIVITY_PRESENTATION[activity_key]
        self.activity_label.setText(f"{icon} {title}")
        self._render_members(members, activity_key)

        self.timeline_list.clear()
        raw_timeline = party.get("timeline")
        timeline = raw_timeline if isinstance(raw_timeline, list) else []
        for raw in timeline:
            if not isinstance(raw, Mapping):
                continue
            kind = str(raw.get("kind") or "")
            marker = "✨" if kind == "interaction" else "🎉" if kind == "started" else "🏠" if kind == "ended" else "🐾"
            actor = str(raw.get("actor_display_name") or "")
            suffix = f" · {actor}" if actor else ""
            self.timeline_list.addItem(
                f"{marker} {str(raw.get('occurred_at') or '').replace('T', ' ')[:16]}{suffix}\n"
                f"{raw.get('title') or ''}：{raw.get('detail') or ''}"
            )
        if not timeline:
            self.timeline_list.addItem("📝 聚会故事刚刚开始，互动后会记录在这里。")
        self._update_actions(party)

    def _clear_member_grid(self) -> None:
        while self.member_grid.count():
            item = self.member_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.member_cards.clear()

    def _render_members(self, members: list[object], activity_key: str) -> None:
        self._clear_member_grid()
        visible = [item for item in members if isinstance(item, Mapping)]
        if not visible:
            self.empty_scene_label = QLabel("还没有聚会成员。邀请好友宠物一起玩吧。")
            self.empty_scene_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty_scene_label.setStyleSheet("color: #667085; padding: 28px;")
            self.member_grid.addWidget(self.empty_scene_label, 0, 0, 1, 2)
            return
        _icon, _title, shared_activity = _ACTIVITY_PRESENTATION[activity_key]
        for index, raw in enumerate(visible[:4]):
            account = _mapping(raw.get("account"))
            pet = _mapping(raw.get("pet"))
            member_status = str(raw.get("status") or "")
            member_activity = shared_activity if member_status == "joined" else _MEMBER_LABELS.get(member_status, "参与聚会")

            card = QFrame()
            card.setProperty("memberCard", True)
            card.setMinimumHeight(126)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(4)

            avatar = QLabel(_pet_icon(pet))
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setStyleSheet("font-size: 34px;")
            card_layout.addWidget(avatar)
            pet_name = QLabel(str(pet.get("name") or "尚未选择宠物"))
            pet_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pet_name.setStyleSheet("font-weight: 750; color: #344054;")
            card_layout.addWidget(pet_name)
            owner_name = "聚会发起宠物" if raw.get("role") == "host" else str(account.get("display_name") or "好友")
            owner = QLabel(owner_name)
            owner.setAlignment(Qt.AlignmentFlag.AlignCenter)
            owner.setStyleSheet("color: #667085;")
            card_layout.addWidget(owner)
            activity = QLabel(member_activity)
            activity.setProperty("activityPill", True)
            activity.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(activity, 0, Qt.AlignmentFlag.AlignCenter)

            row, column = divmod(index, 2)
            self.member_grid.addWidget(card, row, column)
            self.member_cards.append(card)
        self.member_grid.setRowStretch((len(self.member_cards) - 1) // 2 + 1, 1)

    def _update_actions(self, party: dict[str, object] | None) -> None:
        can_invite = bool(party and party.get("can_invite"))
        can_start = bool(party and party.get("can_start"))
        can_cancel = bool(party and party.get("can_cancel"))
        can_end = bool(party and party.get("can_end"))
        can_interact = bool(party and party.get("can_interact"))
        current_member = None
        if party:
            members = party.get("members") if isinstance(party.get("members"), list) else []
            current_member = next(
                (item for item in members if isinstance(item, Mapping) and item.get("is_current_account")),
                None,
            )
        self.invite_username.setEnabled(can_invite)
        self.invite_button.setEnabled(can_invite)
        self.start_button.setEnabled(can_start)
        self.cancel_button.setEnabled(can_cancel)
        self.end_button.setEnabled(can_end)
        self.accept_button.setEnabled(
            bool(current_member and current_member.get("can_accept") and self._current_pet_available)
        )
        self.decline_button.setEnabled(bool(current_member and current_member.get("can_decline")))
        self.leave_button.setEnabled(bool(current_member and current_member.get("can_leave")))
        for button in self.interaction_buttons.values():
            button.setEnabled(can_interact)

    def _create(self) -> None:
        if not self._current_pet_available:
            self.set_status("当前宠物不能参加聚会。", error=True)
            return
        self.create_requested.emit(
            self._current_pet_id,
            self.create_title.text().strip() or "宠物小聚会",
            int(self.create_duration.currentData() or 60),
            int(self.create_count.currentData() or 4),
        )

    def _invite(self) -> None:
        username = self.invite_username.text().strip()
        if not self._current_party_id or not username:
            self.set_status("请输入好友的精确用户名。", error=True)
            return
        self.invite_requested.emit(self._current_party_id, username)

    def _action(self, action: str) -> None:
        if not self._current_party_id:
            return
        if action == "accept":
            if not self._current_pet_available:
                self.set_status("当前宠物不能接受聚会邀请。", error=True)
                return
            self.accept_requested.emit(self._current_party_id, self._current_pet_id)
            return
        self.action_requested.emit(self._current_party_id, action)

    def _interact(self, action: str) -> None:
        if not self._current_party_id:
            return
        self.interaction_requested.emit(
            self._current_party_id,
            action,
            f"desktop-party-{action}-{uuid4()}",
        )
