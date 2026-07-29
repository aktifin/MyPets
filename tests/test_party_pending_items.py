from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from onepic_desktop_pet.party_app import PartyApplication
from onepic_desktop_pet.party_pending_dialog import PartyPendingItemsDialog


def _party_item() -> dict[str, object]:
    return {
        "item_id": "party-1",
        "kind": "party_invitation",
        "title": "好友邀请你参加宠物聚会",
        "detail": "进入聚会选择一只自己管理且当前在家的宠物后回应。",
        "actor_display_name": "好友",
        "pet_id": "pet-host",
        "pet_name": "奶盖",
        "occurred_at": "2026-07-29T10:00:00+08:00",
        "due_at": None,
        "priority": "normal",
        "actions": [],
    }


def test_party_pending_dialog_is_read_only_and_opens_party_scene() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = PartyPendingItemsDialog()
    selected: list[object] = []
    dialog.detail_requested.connect(selected.append)

    dialog.set_items([_party_item()], total_count=1)
    dialog.show()
    app.processEvents()

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    buttons = [button for button in dialog.findChildren(QPushButton)]
    assert "宠物聚会" in labels
    assert any(button.text() == "进入聚会" for button in buttons)
    assert not any(button.text() in {"接受", "拒绝"} for button in buttons)

    next(button for button in buttons if button.text() == "进入聚会").click()
    assert selected == [_party_item()]

    dialog.close()
    app.processEvents()


def test_party_pending_detail_reuses_existing_party_dialog(monkeypatch) -> None:
    loaded: list[str] = []
    opened: list[bool] = []

    class PartyClientStub:
        def load_detail(self, party_id: str) -> None:
            loaded.append(party_id)

    class ApplicationStub:
        party_client = PartyClientStub()

        def open_party_dialog(self) -> None:
            opened.append(True)

    monkeypatch.setattr(
        "onepic_desktop_pet.party_app.QTimer.singleShot",
        lambda _delay, callback: callback(),
    )

    PartyApplication._open_pending_detail(ApplicationStub(), _party_item())

    assert opened == [True]
    assert loaded == ["party-1"]


def test_party_mutation_refreshes_pending_tray_count(monkeypatch) -> None:
    calls: list[str] = []
    application = object.__new__(PartyApplication)
    application._party_dialog = None

    class SessionStub:
        def sync_now(self) -> None:
            calls.append("sync")

    class ClientStub:
        def refresh(self) -> None:
            calls.append("party-refresh")

    application.cloud_session = SessionStub()
    application.party_client = ClientStub()
    application._sync_party_context = lambda: calls.append("context")
    application.refresh_pending_items = lambda: calls.append("pending-refresh")
    monkeypatch.setattr(
        "onepic_desktop_pet.party_app.QTimer.singleShot",
        lambda _delay, callback: callback(),
    )

    PartyApplication._party_mutation_succeeded(
        application,
        "party_accept",
        {"party_id": "party-1"},
    )

    assert calls == ["sync", "party-refresh", "context", "pending-refresh"]
