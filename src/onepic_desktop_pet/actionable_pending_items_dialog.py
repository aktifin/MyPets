"""Pending-items dialog extension with explicit navigation to each authoritative detail view."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QPushButton

from .pending_items_dialog import PendingItemsDialog


class ActionablePendingItemsDialog(PendingItemsDialog):
    detail_requested = Signal(object)

    def _build_card(self, item: Mapping[str, object]) -> QFrame:
        card = super()._build_card(item)
        root = card.layout()
        if root is None or root.count() <= 0:
            return card
        actions = root.itemAt(root.count() - 1).layout()
        if actions is None:
            return card
        detail = QPushButton("查看详情")
        detail.setProperty("secondary", True)
        detail.clicked.connect(
            lambda _checked=False, value=dict(item): self.detail_requested.emit(value)
        )
        actions.insertWidget(1, detail)
        return card
