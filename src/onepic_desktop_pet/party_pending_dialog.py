"""Party invitation presentation for the existing unified pending-items dialog."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtWidgets import QFrame, QPushButton

from .actionable_pending_items_dialog import ActionablePendingItemsDialog
from .pending_items_dialog import _KIND_LABELS

_KIND_LABELS["party_invitation"] = "宠物聚会"


class PartyPendingItemsDialog(ActionablePendingItemsDialog):
    """Keep party invitations read-only and route users to the party scene."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.summary_label.setText("正在读取好友、共同照料、串门、宠物聚会和提醒…")

    def _build_card(self, item: Mapping[str, object]) -> QFrame:
        card = super()._build_card(item)
        if str(item.get("kind") or "") != "party_invitation":
            return card
        for button in card.findChildren(QPushButton):
            if button.text() == "查看详情":
                button.setText("进入聚会")
                break
        return card
