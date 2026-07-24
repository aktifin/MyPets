"""Friends, blocking, pet privacy, and shared-care desktop management UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SocialDialog(QDialog):
    refresh_requested = Signal()
    friend_request_requested = Signal(str)
    friend_request_action_requested = Signal(str, str)
    friend_remove_requested = Signal(str)
    block_requested = Signal(str)
    unblock_requested = Signal(str)
    privacy_save_requested = Signal(str, bool)
    caregiver_invite_requested = Signal(str, str)
    caregiver_invitation_action_requested = Signal(str, str)
    caregiver_remove_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("好友与共同照料")
        self.setModal(False)
        self.resize(860, 620)
        self.account_id: str | None = None
        self.active_pet_id: str | None = None

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.account_label = QLabel("尚未登录")
        self.pet_label = QLabel("当前宠物：无")
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_requested)
        header.addWidget(self.account_label)
        header.addSpacing(18)
        header.addWidget(self.pet_label)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_friends_tab(), "好友")
        self.tabs.addTab(self._build_shared_care_tab(), "共同照料")
        self.tabs.addTab(self._build_blocks_tab(), "屏蔽")
        root.addWidget(self.tabs, 1)

        self.status_label = QLabel("好友和照料关系由服务端确认。")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _build_friends_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        add_row = QHBoxLayout()
        self.friend_username = QLineEdit()
        self.friend_username.setPlaceholderText("输入精确用户名")
        send = QPushButton("发送好友申请")
        send.clicked.connect(self._send_friend_request)
        block = QPushButton("直接屏蔽")
        block.clicked.connect(self._block_username)
        add_row.addWidget(self.friend_username, 1)
        add_row.addWidget(send)
        add_row.addWidget(block)
        layout.addLayout(add_row)

        incoming_group = QGroupBox("待处理好友申请")
        incoming_layout = QVBoxLayout(incoming_group)
        self.friend_requests_table = self._table(["用户", "显示名", "时间"])
        incoming_layout.addWidget(self.friend_requests_table)
        buttons = QHBoxLayout()
        accept = QPushButton("接受")
        accept.clicked.connect(lambda: self._friend_request_action("accept"))
        reject = QPushButton("拒绝")
        reject.clicked.connect(lambda: self._friend_request_action("reject"))
        buttons.addWidget(accept)
        buttons.addWidget(reject)
        buttons.addStretch(1)
        incoming_layout.addLayout(buttons)
        layout.addWidget(incoming_group)

        friends_group = QGroupBox("好友列表")
        friends_layout = QVBoxLayout(friends_group)
        self.friends_table = self._table(["用户名", "显示名", "成为好友时间"])
        friends_layout.addWidget(self.friends_table)
        friend_buttons = QHBoxLayout()
        remove = QPushButton("解除好友")
        remove.clicked.connect(self._remove_friend)
        block_friend = QPushButton("屏蔽好友")
        block_friend.clicked.connect(self._block_friend)
        friend_buttons.addWidget(remove)
        friend_buttons.addWidget(block_friend)
        friend_buttons.addStretch(1)
        friends_layout.addLayout(friend_buttons)
        layout.addWidget(friends_group, 1)
        return page

    def _build_shared_care_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        privacy_group = QGroupBox("当前宠物隐私与远程照料")
        form = QFormLayout(privacy_group)
        self.visibility_combo = QComboBox()
        self.visibility_combo.addItem("仅自己", "private")
        self.visibility_combo.addItem("照料者可见", "caregivers")
        self.visibility_combo.addItem("好友可见", "friends")
        self.visibility_combo.addItem("公开", "public")
        self.remote_care_checkbox = QCheckBox("允许 caregiver 远程投喂、玩耍、清洁、摸摸和休息")
        save_privacy = QPushButton("保存设置")
        save_privacy.clicked.connect(self._save_privacy)
        form.addRow("可见范围", self.visibility_combo)
        form.addRow("远程照料", self.remote_care_checkbox)
        form.addRow("", save_privacy)
        layout.addWidget(privacy_group)

        invite_group = QGroupBox("邀请好友共同照料当前宠物")
        invite_layout = QHBoxLayout(invite_group)
        self.caregiver_username = QLineEdit()
        self.caregiver_username.setPlaceholderText("好友精确用户名")
        self.caregiver_role = QComboBox()
        self.caregiver_role.addItem("照料者", "caregiver")
        self.caregiver_role.addItem("只读查看者", "viewer")
        invite = QPushButton("发送邀请")
        invite.clicked.connect(self._invite_caregiver)
        invite_layout.addWidget(self.caregiver_username, 1)
        invite_layout.addWidget(self.caregiver_role)
        invite_layout.addWidget(invite)
        layout.addWidget(invite_group)

        incoming_group = QGroupBox("收到的共同照料邀请")
        incoming_layout = QVBoxLayout(incoming_group)
        self.caregiver_invites_table = self._table(["宠物", "邀请人", "角色", "时间"])
        incoming_layout.addWidget(self.caregiver_invites_table)
        invite_buttons = QHBoxLayout()
        accept = QPushButton("接受")
        accept.clicked.connect(lambda: self._caregiver_invite_action("accept"))
        reject = QPushButton("拒绝")
        reject.clicked.connect(lambda: self._caregiver_invite_action("reject"))
        invite_buttons.addWidget(accept)
        invite_buttons.addWidget(reject)
        invite_buttons.addStretch(1)
        incoming_layout.addLayout(invite_buttons)
        layout.addWidget(incoming_group)

        caregivers_group = QGroupBox("当前宠物照料者")
        caregivers_layout = QVBoxLayout(caregivers_group)
        self.caregivers_table = self._table(["用户名", "显示名", "角色", "照料贡献"])
        caregivers_layout.addWidget(self.caregivers_table)
        remove = QPushButton("移除选中关系")
        remove.clicked.connect(self._remove_caregiver)
        caregivers_layout.addWidget(remove, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(caregivers_group, 1)
        return page

    def _build_blocks_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.blocks_table = self._table(["用户名", "显示名", "屏蔽时间"])
        layout.addWidget(self.blocks_table)
        unblock = QPushButton("解除屏蔽")
        unblock.clicked.connect(self._unblock)
        layout.addWidget(unblock, alignment=Qt.AlignmentFlag.AlignLeft)
        return page

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def set_context(
        self,
        *,
        account_id: str | None,
        display_name: str,
        active_pet_id: str | None,
        active_pet_name: str,
        can_manage_pet: bool,
    ) -> None:
        self.account_id = account_id
        self.active_pet_id = active_pet_id if can_manage_pet else None
        self.account_label.setText(
            f"账户：{display_name or account_id}" if account_id else "尚未登录"
        )
        self.pet_label.setText(
            f"当前宠物：{active_pet_name}"
            + ("" if can_manage_pet else "（无管理权限）")
            if active_pet_id
            else "当前宠物：无"
        )
        enabled = bool(account_id)
        self.refresh_button.setEnabled(enabled)
        self.visibility_combo.setEnabled(bool(self.active_pet_id))
        self.remote_care_checkbox.setEnabled(bool(self.active_pet_id))
        self.caregiver_username.setEnabled(bool(self.active_pet_id))
        self.caregiver_role.setEnabled(bool(self.active_pet_id))

    def apply_snapshot(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict):
            self.set_status("好友数据响应无效", error=True)
            return
        self._fill_friend_requests(snapshot.get("friend_requests"))
        self._fill_friends(snapshot.get("friends"))
        self._fill_blocks(snapshot.get("blocks"))
        self._fill_invitations(snapshot.get("caregiver_invitations"))
        self._fill_caregivers(snapshot.get("pet_caregivers"))
        privacy = snapshot.get("pet_privacy")
        if isinstance(privacy, dict):
            index = self.visibility_combo.findData(privacy.get("visibility"))
            if index >= 0:
                self.visibility_combo.setCurrentIndex(index)
            self.remote_care_checkbox.setChecked(bool(privacy.get("allow_remote_care")))

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(("错误：" if error else "") + message)

    def _fill_friend_requests(self, payload: object) -> None:
        items = payload.get("incoming", []) if isinstance(payload, dict) else []
        rows = items if isinstance(items, list) else []
        self.friend_requests_table.setRowCount(0)
        for row, item in enumerate(rows):
            if not isinstance(item, dict) or not isinstance(item.get("sender"), dict):
                continue
            sender = item["sender"]
            self.friend_requests_table.insertRow(row)
            first = QTableWidgetItem(str(sender.get("username", "")))
            first.setData(Qt.ItemDataRole.UserRole, str(item.get("request_id", "")))
            self.friend_requests_table.setItem(row, 0, first)
            self.friend_requests_table.setItem(row, 1, QTableWidgetItem(str(sender.get("display_name", ""))))
            self.friend_requests_table.setItem(row, 2, QTableWidgetItem(self._time(item.get("created_at"))))
        self.friend_requests_table.resizeColumnsToContents()

    def _fill_friends(self, payload: object) -> None:
        rows = payload if isinstance(payload, list) else []
        self.friends_table.setRowCount(0)
        for row, item in enumerate(rows):
            if not isinstance(item, dict) or not isinstance(item.get("friend"), dict):
                continue
            friend = item["friend"]
            self.friends_table.insertRow(row)
            first = QTableWidgetItem(str(friend.get("username", "")))
            first.setData(Qt.ItemDataRole.UserRole, str(friend.get("account_id", "")))
            self.friends_table.setItem(row, 0, first)
            self.friends_table.setItem(row, 1, QTableWidgetItem(str(friend.get("display_name", ""))))
            self.friends_table.setItem(row, 2, QTableWidgetItem(self._time(item.get("created_at"))))
        self.friends_table.resizeColumnsToContents()

    def _fill_blocks(self, payload: object) -> None:
        rows = payload if isinstance(payload, list) else []
        self.blocks_table.setRowCount(0)
        for row, item in enumerate(rows):
            if not isinstance(item, dict) or not isinstance(item.get("account"), dict):
                continue
            account = item["account"]
            self.blocks_table.insertRow(row)
            first = QTableWidgetItem(str(account.get("username", "")))
            first.setData(Qt.ItemDataRole.UserRole, str(account.get("account_id", "")))
            self.blocks_table.setItem(row, 0, first)
            self.blocks_table.setItem(row, 1, QTableWidgetItem(str(account.get("display_name", ""))))
            self.blocks_table.setItem(row, 2, QTableWidgetItem(self._time(item.get("created_at"))))
        self.blocks_table.resizeColumnsToContents()

    def _fill_invitations(self, payload: object) -> None:
        items = payload.get("incoming", []) if isinstance(payload, dict) else []
        rows = items if isinstance(items, list) else []
        self.caregiver_invites_table.setRowCount(0)
        for row, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            pet = item.get("pet") if isinstance(item.get("pet"), dict) else {}
            inviter = item.get("invited_by") if isinstance(item.get("invited_by"), dict) else {}
            self.caregiver_invites_table.insertRow(row)
            first = QTableWidgetItem(str(pet.get("name", "")))
            first.setData(Qt.ItemDataRole.UserRole, str(item.get("invitation_id", "")))
            self.caregiver_invites_table.setItem(row, 0, first)
            self.caregiver_invites_table.setItem(row, 1, QTableWidgetItem(str(inviter.get("display_name", ""))))
            self.caregiver_invites_table.setItem(row, 2, QTableWidgetItem(str(item.get("role", ""))))
            self.caregiver_invites_table.setItem(row, 3, QTableWidgetItem(self._time(item.get("created_at"))))
        self.caregiver_invites_table.resizeColumnsToContents()

    def _fill_caregivers(self, payload: object) -> None:
        rows = payload if isinstance(payload, list) else []
        self.caregivers_table.setRowCount(0)
        for row, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            account = item.get("account") if isinstance(item.get("account"), dict) else {}
            relation = item.get("relation") if isinstance(item.get("relation"), dict) else {}
            self.caregivers_table.insertRow(row)
            first = QTableWidgetItem(str(account.get("username", "")))
            first.setData(Qt.ItemDataRole.UserRole, str(account.get("account_id", "")))
            self.caregivers_table.setItem(row, 0, first)
            self.caregivers_table.setItem(row, 1, QTableWidgetItem(str(account.get("display_name", ""))))
            self.caregivers_table.setItem(row, 2, QTableWidgetItem(str(relation.get("role", ""))))
            self.caregivers_table.setItem(row, 3, QTableWidgetItem(str(relation.get("care_contribution", 0))))
        self.caregivers_table.resizeColumnsToContents()

    @staticmethod
    def _selected_id(table: QTableWidget) -> str | None:
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    def _send_friend_request(self) -> None:
        username = self.friend_username.text().strip()
        if username:
            self.friend_request_requested.emit(username)

    def _block_username(self) -> None:
        username = self.friend_username.text().strip()
        if username:
            self.block_requested.emit(username)

    def _friend_request_action(self, action: str) -> None:
        request_id = self._selected_id(self.friend_requests_table)
        if request_id:
            self.friend_request_action_requested.emit(request_id, action)

    def _remove_friend(self) -> None:
        account_id = self._selected_id(self.friends_table)
        if account_id:
            self.friend_remove_requested.emit(account_id)

    def _block_friend(self) -> None:
        row = self.friends_table.currentRow()
        item = self.friends_table.item(row, 0) if row >= 0 else None
        if item and item.text().strip():
            self.block_requested.emit(item.text().strip())

    def _unblock(self) -> None:
        account_id = self._selected_id(self.blocks_table)
        if account_id:
            self.unblock_requested.emit(account_id)

    def _save_privacy(self) -> None:
        self.privacy_save_requested.emit(
            str(self.visibility_combo.currentData()),
            self.remote_care_checkbox.isChecked(),
        )

    def _invite_caregiver(self) -> None:
        username = self.caregiver_username.text().strip()
        if username:
            self.caregiver_invite_requested.emit(username, str(self.caregiver_role.currentData()))

    def _caregiver_invite_action(self, action: str) -> None:
        invitation_id = self._selected_id(self.caregiver_invites_table)
        if invitation_id:
            self.caregiver_invitation_action_requested.emit(invitation_id, action)

    def _remove_caregiver(self) -> None:
        account_id = self._selected_id(self.caregivers_table)
        if account_id and self.active_pet_id:
            self.caregiver_remove_requested.emit(self.active_pet_id, account_id)

    @staticmethod
    def _time(value: object) -> str:
        return str(value or "").replace("T", " ")[:16]
