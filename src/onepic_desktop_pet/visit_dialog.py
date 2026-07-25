"""Desktop UI for requesting, accepting, monitoring, and recalling pet visits."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class VisitDialog(QDialog):
    refresh_requested = Signal()
    friend_pets_requested = Signal(str)
    visit_request_requested = Signal(str, str, int, str)
    visit_action_requested = Signal(str, str)
    visit_recall_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("异步串门")
        self.setModal(False)
        self.resize(920, 660)
        self.account_id: str | None = None
        self.active_pet_id: str | None = None

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.account_label = QLabel("尚未登录")
        self.pet_label = QLabel("来访宠物：无")
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_requested)
        header.addWidget(self.account_label)
        header.addSpacing(18)
        header.addWidget(self.pet_label)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        request_group = QGroupBox("向好友发起串门")
        request_layout = QVBoxLayout(request_group)
        friend_row = QHBoxLayout()
        self.friend_combo = QComboBox()
        self.friend_combo.setMinimumWidth(220)
        self.load_pets_button = QPushButton("加载好友宠物")
        self.load_pets_button.clicked.connect(self._load_friend_pets)
        self.host_pet_combo = QComboBox()
        self.host_pet_combo.setMinimumWidth(220)
        friend_row.addWidget(QLabel("好友"))
        friend_row.addWidget(self.friend_combo, 1)
        friend_row.addWidget(self.load_pets_button)
        friend_row.addWidget(QLabel("接待宠物"))
        friend_row.addWidget(self.host_pet_combo, 1)
        request_layout.addLayout(friend_row)

        detail_row = QHBoxLayout()
        self.duration_combo = QComboBox()
        for minutes, label in ((30, "30 分钟"), (60, "1 小时"), (120, "2 小时"), (240, "4 小时")):
            self.duration_combo.addItem(label, minutes)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("可选留言，最多 200 字")
        self.send_button = QPushButton("发送串门申请")
        self.send_button.clicked.connect(self._send_visit)
        detail_row.addWidget(QLabel("时长"))
        detail_row.addWidget(self.duration_combo)
        detail_row.addWidget(QLabel("留言"))
        detail_row.addWidget(self.note_edit, 1)
        detail_row.addWidget(self.send_button)
        request_layout.addLayout(detail_row)
        root.addWidget(request_group)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_requests_tab(), "申请")
        self.tabs.addTab(self._build_active_tab(), "进行中")
        self.tabs.addTab(self._build_history_tab(), "历史")
        root.addWidget(self.tabs, 1)

        self.status_label = QLabel("串门关系由服务端确认，到期后自动返家。")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _build_requests_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        incoming_group = QGroupBox("收到的申请")
        incoming_layout = QVBoxLayout(incoming_group)
        self.incoming_table = self._table(["来访宠物", "申请人", "接待宠物", "时长", "留言", "时间"])
        incoming_layout.addWidget(self.incoming_table)
        incoming_actions = QHBoxLayout()
        accept = QPushButton("接受")
        accept.clicked.connect(lambda: self._request_action(self.incoming_table, "accept"))
        reject = QPushButton("拒绝")
        reject.clicked.connect(lambda: self._request_action(self.incoming_table, "reject"))
        incoming_actions.addWidget(accept)
        incoming_actions.addWidget(reject)
        incoming_actions.addStretch(1)
        incoming_layout.addLayout(incoming_actions)
        layout.addWidget(incoming_group)

        outgoing_group = QGroupBox("发出的申请")
        outgoing_layout = QVBoxLayout(outgoing_group)
        self.outgoing_table = self._table(["来访宠物", "好友", "接待宠物", "时长", "留言", "时间"])
        outgoing_layout.addWidget(self.outgoing_table)
        cancel = QPushButton("取消申请")
        cancel.clicked.connect(lambda: self._request_action(self.outgoing_table, "cancel"))
        outgoing_layout.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(outgoing_group)
        return page

    def _build_active_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.active_table = self._table(["来访宠物", "接待宠物", "对方", "开始", "预计返家", "留言"])
        layout.addWidget(self.active_table)
        actions = QHBoxLayout()
        recall = QPushButton("召回来访宠物")
        recall.clicked.connect(self._recall)
        actions.addWidget(recall)
        actions.addStretch(1)
        layout.addLayout(actions)
        return page

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.history_table = self._table(["来访宠物", "接待宠物", "对方", "状态", "结束原因", "时间"])
        layout.addWidget(self.history_table)
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
        can_request: bool,
    ) -> None:
        self.account_id = account_id
        self.active_pet_id = active_pet_id if can_request else None
        self.account_label.setText(
            f"账户：{display_name or account_id}" if account_id else "尚未登录"
        )
        self.pet_label.setText(
            f"来访宠物：{active_pet_name}"
            + ("" if can_request else "（需要 owner 或 co_owner 权限）")
            if active_pet_id
            else "来访宠物：无"
        )
        connected = bool(account_id)
        self.refresh_button.setEnabled(connected)
        self.friend_combo.setEnabled(connected and bool(self.active_pet_id))
        self.load_pets_button.setEnabled(connected and bool(self.active_pet_id))
        self.host_pet_combo.setEnabled(connected and bool(self.active_pet_id))
        self.duration_combo.setEnabled(connected and bool(self.active_pet_id))
        self.note_edit.setEnabled(connected and bool(self.active_pet_id))
        self.send_button.setEnabled(connected and bool(self.active_pet_id))

    def apply_snapshot(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict):
            self.set_status("串门数据响应无效", error=True)
            return
        self._fill_friends(snapshot.get("friends"))
        self._fill_friend_pets(snapshot.get("friend_pets"))
        visits = snapshot.get("visits")
        if isinstance(visits, dict):
            self._fill_visits(self.incoming_table, visits.get("incoming_requests"), history=False)
            self._fill_visits(self.outgoing_table, visits.get("outgoing_requests"), history=False)
            self._fill_active(visits.get("active"))
            self._fill_history(visits.get("history"))

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(("错误：" if error else "") + message)

    def _fill_friends(self, payload: object) -> None:
        current = self.friend_combo.currentData()
        self.friend_combo.blockSignals(True)
        self.friend_combo.clear()
        rows = payload if isinstance(payload, list) else []
        for item in rows:
            if not isinstance(item, dict) or not isinstance(item.get("friend"), dict):
                continue
            friend = item["friend"]
            account_id = str(friend.get("account_id", ""))
            username = str(friend.get("username", ""))
            display = str(friend.get("display_name", ""))
            if account_id and username:
                self.friend_combo.addItem(f"{display or username}（{username}）", (account_id, username))
        if current is not None:
            for index in range(self.friend_combo.count()):
                if self.friend_combo.itemData(index) == current:
                    self.friend_combo.setCurrentIndex(index)
                    break
        self.friend_combo.blockSignals(False)

    def _fill_friend_pets(self, payload: object) -> None:
        self.host_pet_combo.clear()
        rows = payload if isinstance(payload, list) else []
        for item in rows:
            if not isinstance(item, dict):
                continue
            pet_id = str(item.get("pet_id", ""))
            name = str(item.get("name", ""))
            presence = str(item.get("presence", ""))
            if pet_id:
                label = f"{name or pet_id} · {self._presence_label(presence)}"
                self.host_pet_combo.addItem(label, pet_id)

    def _fill_visits(self, table: QTableWidget, payload: object, *, history: bool) -> None:
        rows = payload if isinstance(payload, list) else []
        table.setRowCount(0)
        for item in rows:
            if not isinstance(item, dict):
                continue
            visitor = item.get("visitor_pet") if isinstance(item.get("visitor_pet"), dict) else {}
            host_pet = item.get("host_pet") if isinstance(item.get("host_pet"), dict) else {}
            other = item.get("requester") if table is self.incoming_table else item.get("host")
            other = other if isinstance(other, dict) else {}
            row = table.rowCount()
            table.insertRow(row)
            first = QTableWidgetItem(str(visitor.get("name", "")))
            first.setData(Qt.ItemDataRole.UserRole, str(item.get("visit_id", "")))
            table.setItem(row, 0, first)
            table.setItem(row, 1, QTableWidgetItem(str(other.get("display_name", ""))))
            table.setItem(row, 2, QTableWidgetItem(str(host_pet.get("name", ""))))
            table.setItem(row, 3, QTableWidgetItem(f"{item.get('duration_minutes', 0)} 分钟"))
            table.setItem(row, 4, QTableWidgetItem(str(item.get("note", ""))))
            table.setItem(row, 5, QTableWidgetItem(self._time(item.get("created_at"))))
        table.resizeColumnsToContents()

    def _fill_active(self, payload: object) -> None:
        rows = payload if isinstance(payload, list) else []
        self.active_table.setRowCount(0)
        for item in rows:
            if not isinstance(item, dict):
                continue
            visitor = item.get("visitor_pet") if isinstance(item.get("visitor_pet"), dict) else {}
            host_pet = item.get("host_pet") if isinstance(item.get("host_pet"), dict) else {}
            requester = item.get("requester") if isinstance(item.get("requester"), dict) else {}
            host = item.get("host") if isinstance(item.get("host"), dict) else {}
            other = host if str(requester.get("account_id", "")) == self.account_id else requester
            row = self.active_table.rowCount()
            self.active_table.insertRow(row)
            first = QTableWidgetItem(str(visitor.get("name", "")))
            first.setData(Qt.ItemDataRole.UserRole, str(item.get("visit_id", "")))
            first.setData(Qt.ItemDataRole.UserRole + 1, bool(item.get("can_recall")))
            self.active_table.setItem(row, 0, first)
            self.active_table.setItem(row, 1, QTableWidgetItem(str(host_pet.get("name", ""))))
            self.active_table.setItem(row, 2, QTableWidgetItem(str(other.get("display_name", ""))))
            self.active_table.setItem(row, 3, QTableWidgetItem(self._time(item.get("started_at"))))
            self.active_table.setItem(row, 4, QTableWidgetItem(self._time(item.get("scheduled_end_at"))))
            self.active_table.setItem(row, 5, QTableWidgetItem(str(item.get("note", ""))))
        self.active_table.resizeColumnsToContents()

    def _fill_history(self, payload: object) -> None:
        rows = payload if isinstance(payload, list) else []
        self.history_table.setRowCount(0)
        for item in rows:
            if not isinstance(item, dict):
                continue
            visitor = item.get("visitor_pet") if isinstance(item.get("visitor_pet"), dict) else {}
            host_pet = item.get("host_pet") if isinstance(item.get("host_pet"), dict) else {}
            requester = item.get("requester") if isinstance(item.get("requester"), dict) else {}
            host = item.get("host") if isinstance(item.get("host"), dict) else {}
            other = host if str(requester.get("account_id", "")) == self.account_id else requester
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self.history_table.setItem(row, 0, QTableWidgetItem(str(visitor.get("name", ""))))
            self.history_table.setItem(row, 1, QTableWidgetItem(str(host_pet.get("name", ""))))
            self.history_table.setItem(row, 2, QTableWidgetItem(str(other.get("display_name", ""))))
            self.history_table.setItem(row, 3, QTableWidgetItem(self._status_label(str(item.get("status", "")))))
            self.history_table.setItem(row, 4, QTableWidgetItem(self._reason_label(str(item.get("completion_reason", "")))))
            self.history_table.setItem(row, 5, QTableWidgetItem(self._time(item.get("completed_at") or item.get("responded_at"))))
        self.history_table.resizeColumnsToContents()

    def _load_friend_pets(self) -> None:
        value = self.friend_combo.currentData()
        if isinstance(value, tuple) and value and value[0]:
            self.friend_pets_requested.emit(str(value[0]))

    def _send_visit(self) -> None:
        friend = self.friend_combo.currentData()
        host_pet_id = self.host_pet_combo.currentData()
        if not isinstance(friend, tuple) or len(friend) < 2 or not host_pet_id:
            self.set_status("请选择好友并加载可接待宠物", error=True)
            return
        self.visit_request_requested.emit(
            str(friend[1]),
            str(host_pet_id),
            int(self.duration_combo.currentData()),
            self.note_edit.text().strip(),
        )

    def _request_action(self, table: QTableWidget, action: str) -> None:
        visit_id = self._selected_id(table)
        if visit_id:
            self.visit_action_requested.emit(visit_id, action)

    def _recall(self) -> None:
        row = self.active_table.currentRow()
        item = self.active_table.item(row, 0) if row >= 0 else None
        if item is None:
            return
        if not bool(item.data(Qt.ItemDataRole.UserRole + 1)):
            self.set_status("只有来访宠物的主人可以召回", error=True)
            return
        visit_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if visit_id:
            self.visit_recall_requested.emit(visit_id)

    @staticmethod
    def _selected_id(table: QTableWidget) -> str | None:
        row = table.currentRow()
        item = table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    @staticmethod
    def _time(value: object) -> str:
        return str(value or "").replace("T", " ")[:16]

    @staticmethod
    def _presence_label(value: str) -> str:
        return {"home": "在家", "resting": "休息中", "visiting": "串门中"}.get(value, value)

    @staticmethod
    def _status_label(value: str) -> str:
        return {
            "rejected": "已拒绝",
            "cancelled": "已取消",
            "completed": "已完成",
            "recalled": "已召回",
            "expired": "已过期",
        }.get(value, value)

    @staticmethod
    def _reason_label(value: str) -> str:
        return {
            "visit_rejected": "接待方拒绝",
            "visit_cancelled": "申请方取消",
            "visit_recalled": "主人主动召回",
            "visit_auto_returned": "到期自动返家",
            "account_blocked": "账户关系已屏蔽",
        }.get(value, value)
