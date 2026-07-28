"""Windows dialog for filtering customer processing history and reopening details."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_KIND_LABELS = {
    "friend_request": "好友申请",
    "caregiver_invitation": "共同照料",
    "visit": "串门",
    "reminder": "提醒",
}
_ACTION_LABELS = {
    "accepted": "已接受",
    "rejected": "已拒绝",
    "cancelled": "已取消",
    "completed": "已完成",
    "snoozed": "稍后提醒",
    "dismissed": "已忽略",
    "returned": "已返家",
    "expired": "已过期",
}


class CustomerHistoryDialog(QDialog):
    refresh_requested = Signal(str, int)
    detail_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("处理记录")
        self.setModal(False)
        self.resize(900, 600)
        self.setMinimumSize(700, 460)
        self._items: list[dict[str, object]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("处理记录")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #344054;")
        self.summary_label = QLabel("好友、共同照料、串门和提醒的处理结果集中保留。")
        self.summary_label.setStyleSheet("color: #667085;")
        copy.addWidget(title)
        copy.addWidget(self.summary_label)
        header.addLayout(copy, 1)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("全部类型", "all")
        self.kind_combo.addItem("好友申请", "friend_request")
        self.kind_combo.addItem("共同照料", "caregiver_invitation")
        self.kind_combo.addItem("串门", "visit")
        self.kind_combo.addItem("提醒", "reminder")
        header.addWidget(self.kind_combo)

        self.days_combo = QComboBox()
        self.days_combo.addItem("最近 7 天", 7)
        self.days_combo.addItem("最近 30 天", 30)
        self.days_combo.addItem("最近 90 天", 90)
        self.days_combo.addItem("最近一年", 365)
        self.days_combo.addItem("全部记录", 0)
        self.days_combo.setCurrentIndex(1)
        header.addWidget(self.days_combo)

        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self._request_refresh)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["类型", "结果", "内容", "时间", "相关对象"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemDoubleClicked.connect(lambda _item: self._open_selected())
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("双击记录或选择后打开相关详情。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #667085;")
        footer.addWidget(self.status_label, 1)
        self.open_button = QPushButton("打开详情")
        self.open_button.clicked.connect(self._open_selected)
        self.open_button.setEnabled(False)
        footer.addWidget(self.open_button)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.hide)
        footer.addWidget(close_button)
        root.addLayout(footer)
        self.table.itemSelectionChanged.connect(
            lambda: self.open_button.setEnabled(self.table.currentRow() >= 0)
        )

    def current_filters(self) -> tuple[str, int]:
        return str(self.kind_combo.currentData() or "all"), int(self.days_combo.currentData() or 0)

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.kind_combo.setEnabled(not busy)
        self.days_combo.setEnabled(not busy)
        if busy:
            self.set_status("正在读取处理记录…")

    def set_history(self, payload: object) -> None:
        if not isinstance(payload, dict):
            self.set_status("处理记录响应无效", error=True)
            return
        raw_items = payload.get("items")
        values = raw_items if isinstance(raw_items, list) else []
        self._items = [dict(item) for item in values if isinstance(item, dict)]
        total = max(0, int(payload.get("count") or 0))
        self.summary_label.setText(f"当前筛选范围共 {total} 条处理记录")
        self.table.setRowCount(0)
        for item in self._items:
            self._append_item(item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.open_button.setEnabled(False)
        self.set_busy(False)
        self.set_status("处理记录已刷新。" if self._items else "当前筛选范围内没有处理记录。")

    def set_items(self, items: Sequence[Mapping[str, object]], *, total_count: int) -> None:
        self.set_history({"count": total_count, "items": [dict(item) for item in items]})

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #b42318;" if error else "color: #067647;")

    def _append_item(self, item: dict[str, object]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        kind = str(item.get("kind") or "")
        action = str(item.get("action") or "")
        first = QTableWidgetItem(_KIND_LABELS.get(kind, kind or "处理记录"))
        first.setData(Qt.ItemDataRole.UserRole, item)
        self.table.setItem(row, 0, first)
        self.table.setItem(row, 1, QTableWidgetItem(_ACTION_LABELS.get(action, action)))
        title = str(item.get("title") or "")
        detail = str(item.get("detail") or "")
        self.table.setItem(row, 2, QTableWidgetItem(f"{title}\n{detail}".strip()))
        self.table.setItem(row, 3, QTableWidgetItem(self._time(item.get("occurred_at"))))
        target = str(item.get("target_label") or "查看详情")
        self.table.setItem(row, 4, QTableWidgetItem(target))

    def _request_refresh(self) -> None:
        kind, days = self.current_filters()
        self.set_busy(True)
        self.refresh_requested.emit(kind, days)

    def _open_selected(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(payload, dict):
            self.detail_requested.emit(dict(payload))

    @staticmethod
    def _time(value: object) -> str:
        return str(value or "").replace("T", " ")[:16]
