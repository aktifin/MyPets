"""Visit dialog extension that presents one customer-readable lifecycle timeline."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .visit_dialog import VisitDialog


_TIMELINE_KIND_LABELS = {
    "requested": "已申请",
    "accepted": "已接受",
    "arrived": "已到达",
    "interaction": "互动",
    "rejected": "已拒绝",
    "cancelled": "已取消",
    "returned": "已返家",
    "expired": "已过期",
}


class ActionableVisitDialog(VisitDialog):
    timeline_requested = Signal(str)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        timeline_page = QWidget()
        timeline_layout = QVBoxLayout(timeline_page)
        heading = QHBoxLayout()
        self.timeline_summary = QLabel("选择一条串门记录查看完整过程。")
        self.timeline_summary.setWordWrap(True)
        heading.addWidget(self.timeline_summary, 1)
        refresh = QPushButton("刷新所选时间线")
        refresh.clicked.connect(self._request_selected_timeline)
        heading.addWidget(refresh)
        timeline_layout.addLayout(heading)
        self.timeline_table = QTableWidget(0, 4)
        self.timeline_table.setHorizontalHeaderLabels(["阶段", "内容", "参与者", "时间"])
        self.timeline_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.timeline_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.timeline_table.verticalHeader().setVisible(False)
        self.timeline_table.horizontalHeader().setStretchLastSection(True)
        timeline_layout.addWidget(self.timeline_table, 1)
        self.tabs.addTab(timeline_page, "时间线")

        open_row = QHBoxLayout()
        open_button = QPushButton("查看所选串门时间线")
        open_button.clicked.connect(self._request_selected_timeline)
        open_row.addWidget(open_button)
        open_row.addStretch(1)
        root = self.layout()
        if root is not None:
            root.insertLayout(max(0, root.count() - 1), open_row)

    def show_timeline(self, payload: object) -> None:
        if not isinstance(payload, dict):
            self.set_status("串门时间线响应无效", error=True)
            return
        visitor_name = str(payload.get("visitor_pet_name") or "来访宠物")
        host_name = str(payload.get("host_pet_name") or "接待宠物")
        status = self._status_label(str(payload.get("status") or ""))
        self.timeline_summary.setText(f"{visitor_name} → {host_name} · {status}")
        self.timeline_table.setRowCount(0)
        raw_entries = payload.get("entries")
        entries = raw_entries if isinstance(raw_entries, list) else []
        for raw in entries:
            if not isinstance(raw, Mapping):
                continue
            row = self.timeline_table.rowCount()
            self.timeline_table.insertRow(row)
            self.timeline_table.setItem(
                row,
                0,
                QTableWidgetItem(_TIMELINE_KIND_LABELS.get(str(raw.get("kind") or ""), str(raw.get("kind") or ""))),
            )
            title = str(raw.get("title") or "")
            detail = str(raw.get("detail") or "")
            self.timeline_table.setItem(row, 1, QTableWidgetItem(f"{title}\n{detail}".strip()))
            self.timeline_table.setItem(
                row,
                2,
                QTableWidgetItem(str(raw.get("actor_display_name") or "系统")),
            )
            self.timeline_table.setItem(row, 3, QTableWidgetItem(self._time(raw.get("occurred_at"))))
        self.timeline_table.resizeRowsToContents()
        self.timeline_table.resizeColumnsToContents()
        self.tabs.setCurrentIndex(self.tabs.count() - 1)
        self.set_status("串门时间线已更新")

    def focus_visit(self, visit_id: str) -> bool:
        value = visit_id.strip()
        if not value:
            return False
        for tab_index, table in (
            (0, self.incoming_table),
            (0, self.outgoing_table),
            (1, self.active_table),
            (2, self.history_table),
        ):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and str(item.data(Qt.ItemDataRole.UserRole) or "") == value:
                    table.selectRow(row)
                    self.tabs.setCurrentIndex(tab_index)
                    return True
        return False

    def _request_selected_timeline(self) -> None:
        visit_id = self._selected_visit_id()
        if not visit_id:
            self.set_status("请先在申请、进行中或历史列表选择一条串门记录", error=True)
            return
        self.timeline_requested.emit(visit_id)
        self.set_status("正在读取串门时间线…")

    def _selected_visit_id(self) -> str | None:
        current = self.tabs.currentIndex()
        tables = (
            (self.incoming_table, self.outgoing_table)
            if current == 0
            else ((self.active_table,) if current == 1 else ((self.history_table,) if current == 2 else ()))
        )
        for table in tables:
            value = self._selected_id(table)
            if value:
                return value
        for table in (self.active_table, self.history_table, self.incoming_table, self.outgoing_table):
            value = self._selected_id(table)
            if value:
                return value
        return None
