"""Single-window Windows party scene; it never creates additional desktop pet windows."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

DESKTOP_PARTY_WINDOW_LIMIT = 2

_STATUS_LABELS = {
    "open": "等待开始",
    "active": "进行中",
    "completed": "已结束",
    "cancelled": "已取消",
}
_MEMBER_LABELS = {
    "invited": "待回应",
    "accepted": "已确认",
    "declined": "已谢绝",
    "joined": "在场",
    "left": "已离场",
    "completed": "已完成",
    "expired": "已失效",
}
_INTERACTION_LABELS = {
    "greet_circle": "围圈打招呼",
    "play_together": "一起玩耍",
    "group_photo": "留下合影记录",
    "rest_together": "一起休息",
}


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
        self.setWindowTitle("宠物聚会")
        self.setModal(False)
        self.resize(1040, 680)
        self.setMinimumSize(820, 560)
        self._parties: dict[str, dict[str, object]] = {}
        self._current_party_id = ""
        self._current_pet_id = ""
        self._current_pet_name = ""
        self._current_pet_available = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("多宠物聚会")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #344054;")
        self.summary_label = QLabel(
            f"全部成员只在本场景面板中呈现；桌面常驻宠物窗口上限始终为 {DESKTOP_PARTY_WINDOW_LIMIT} 只。"
        )
        self.summary_label.setStyleSheet("color: #667085;")
        self.summary_label.setWordWrap(True)
        copy.addWidget(title)
        copy.addWidget(self.summary_label)
        header.addLayout(copy, 1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_requested)
        header.addWidget(self.refresh_button)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.hide)
        header.addWidget(close_button)
        root.addLayout(header)

        create_row = QHBoxLayout()
        self.current_pet_label = QLabel("当前宠物：未选择")
        self.current_pet_label.setMinimumWidth(180)
        create_row.addWidget(self.current_pet_label)
        self.create_title = QLineEdit("宠物小聚会")
        self.create_title.setMaxLength(80)
        self.create_title.setPlaceholderText("聚会名称")
        create_row.addWidget(self.create_title, 1)
        self.create_count = QComboBox()
        self.create_count.addItem("最多 2 只", 2)
        self.create_count.addItem("最多 3 只", 3)
        self.create_count.addItem("最多 4 只", 4)
        self.create_count.setCurrentIndex(2)
        create_row.addWidget(self.create_count)
        self.create_duration = QComboBox()
        for minutes in (30, 60, 120, 180):
            self.create_duration.addItem(f"{minutes} 分钟", minutes)
        self.create_duration.setCurrentIndex(1)
        create_row.addWidget(self.create_duration)
        self.create_button = QPushButton("发起聚会")
        self.create_button.setEnabled(False)
        self.create_button.clicked.connect(self._create)
        create_row.addWidget(self.create_button)
        root.addLayout(create_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("我的聚会与邀请"))
        self.party_list = QListWidget()
        self.party_list.currentItemChanged.connect(self._select_party)
        left_layout.addWidget(self.party_list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self.party_title_label = QLabel("请选择一场聚会")
        self.party_title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        right_layout.addWidget(self.party_title_label)
        self.party_meta_label = QLabel("")
        self.party_meta_label.setStyleSheet("color: #667085;")
        self.party_meta_label.setWordWrap(True)
        right_layout.addWidget(self.party_meta_label)

        self.member_table = QTableWidget(0, 4)
        self.member_table.setHorizontalHeaderLabels(["参与账户", "宠物", "身份", "状态"])
        self.member_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.member_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.member_table.verticalHeader().setVisible(False)
        self.member_table.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self.member_table, 1)

        invite_form = QFormLayout()
        invite_row = QHBoxLayout()
        self.invite_username = QLineEdit()
        self.invite_username.setPlaceholderText("好友精确用户名")
        self.invite_username.setMaxLength(64)
        invite_row.addWidget(self.invite_username, 1)
        self.invite_button = QPushButton("邀请好友")
        self.invite_button.clicked.connect(self._invite)
        invite_row.addWidget(self.invite_button)
        invite_form.addRow("增加成员", invite_row)
        right_layout.addLayout(invite_form)

        action_row = QHBoxLayout()
        self.accept_button = QPushButton("用当前宠物接受")
        self.accept_button.clicked.connect(lambda: self._action("accept"))
        action_row.addWidget(self.accept_button)
        self.decline_button = QPushButton("谢绝")
        self.decline_button.clicked.connect(lambda: self._action("decline"))
        action_row.addWidget(self.decline_button)
        self.start_button = QPushButton("开始聚会")
        self.start_button.clicked.connect(lambda: self._action("start"))
        action_row.addWidget(self.start_button)
        self.leave_button = QPushButton("提前离场")
        self.leave_button.clicked.connect(lambda: self._action("leave"))
        action_row.addWidget(self.leave_button)
        self.cancel_button = QPushButton("取消聚会")
        self.cancel_button.clicked.connect(lambda: self._action("cancel"))
        action_row.addWidget(self.cancel_button)
        self.end_button = QPushButton("结束聚会")
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

        right_layout.addWidget(QLabel("聚会时间线"))
        self.timeline_list = QListWidget()
        right_layout.addWidget(self.timeline_list, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        self.status_label = QLabel("聚会不会改变宠物归属或共同照料权限。")
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
        suffix = "可参加" if self._current_pet_available else "当前不可参加"
        self.current_pet_label.setText(
            f"当前宠物：{name or '未选择'} · {suffix}"
        )
        self.create_button.setEnabled(self._current_pet_available)
        self._update_actions(self._current_party())

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        if busy:
            self.set_status("正在读取聚会数据…")

    def set_snapshot(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            self.set_status("聚会列表响应无效", error=True)
            return
        selected_id = self._current_party_id
        self._parties.clear()
        self.party_list.clear()
        categories = (
            ("待回应", payload.get("invitations")),
            ("等待开始", payload.get("open")),
            ("进行中", payload.get("active")),
            ("历史", payload.get("history")),
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
                item = QListWidgetItem(
                    f"[{category}] {party.get('title') or '宠物聚会'} · "
                    f"{_STATUS_LABELS.get(str(party.get('status') or ''), party.get('status') or '')}"
                )
                item.setData(Qt.ItemDataRole.UserRole, party_id)
                self.party_list.addItem(item)
                if party_id == selected_id:
                    self.party_list.setCurrentItem(item)
        if not self._parties:
            self._current_party_id = ""
            self.party_title_label.setText("暂无聚会")
            self.party_meta_label.setText("可使用上方当前宠物发起一场最多四只宠物的小聚会。")
            self.member_table.setRowCount(0)
            self.timeline_list.clear()
            self._update_actions(None)
        elif self.party_list.currentRow() < 0:
            self.party_list.setCurrentRow(0)
        self.set_busy(False)
        self.set_status(
            f"已同步 {len(self._parties)} 场聚会；所有成员仍共用一个场景面板。"
        )

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
        self.set_status("聚会成员与时间线已刷新。")

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

    def _render_party(self, party: dict[str, object]) -> None:
        self.party_title_label.setText(str(party.get("title") or "宠物聚会"))
        status = str(party.get("status") or "")
        joined = int(party.get("joined_count") or 0)
        accepted = int(party.get("accepted_count") or 0)
        maximum = int(party.get("max_members") or 0)
        limit = int(party.get("desktop_window_limit") or DESKTOP_PARTY_WINDOW_LIMIT)
        self.party_meta_label.setText(
            f"{_STATUS_LABELS.get(status, status)} · 已确认 {accepted}/{maximum} · 在场 {joined} · "
            f"单场景呈现 · 桌面常驻上限 {limit} 只"
        )
        raw_members = party.get("members")
        members = raw_members if isinstance(raw_members, list) else []
        self.member_table.setRowCount(0)
        for raw in members:
            if not isinstance(raw, Mapping):
                continue
            row = self.member_table.rowCount()
            self.member_table.insertRow(row)
            account = raw.get("account") if isinstance(raw.get("account"), Mapping) else {}
            pet = raw.get("pet") if isinstance(raw.get("pet"), Mapping) else {}
            self.member_table.setItem(row, 0, QTableWidgetItem(str(account.get("display_name") or "")))
            self.member_table.setItem(row, 1, QTableWidgetItem(str(pet.get("name") or "尚未选择")))
            self.member_table.setItem(
                row,
                2,
                QTableWidgetItem("发起人" if raw.get("role") == "host" else "成员"),
            )
            member_status = str(raw.get("status") or "")
            self.member_table.setItem(
                row,
                3,
                QTableWidgetItem(_MEMBER_LABELS.get(member_status, member_status)),
            )
        self.member_table.resizeColumnsToContents()
        self.member_table.horizontalHeader().setStretchLastSection(True)

        self.timeline_list.clear()
        raw_timeline = party.get("timeline")
        timeline = raw_timeline if isinstance(raw_timeline, list) else []
        for raw in timeline:
            if not isinstance(raw, Mapping):
                continue
            actor = str(raw.get("actor_display_name") or "")
            suffix = f" · {actor}" if actor else ""
            self.timeline_list.addItem(
                f"{str(raw.get('occurred_at') or '').replace('T', ' ')[:16]}{suffix}\n"
                f"{raw.get('title') or ''}：{raw.get('detail') or ''}"
            )
        self._update_actions(party)

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
            self.set_status("请输入好友精确用户名。", error=True)
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
