"""GuestPetWindow, AwayIndicator, and deterministic dual-pet placement tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from onepic_desktop_pet.presentation.away_indicator import AwayIndicator
from onepic_desktop_pet.presentation.dual_pet_scene import DualPetSceneCoordinator
from onepic_desktop_pet.presentation.guest_pet_window import GuestPetWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_guest_window_requests_only_enabled_actions_and_animates_after_confirmation(qapp) -> None:
    window = GuestPetWindow(
        visit_id="visit-123",
        visitor_pet_id="pet-456",
        visitor_pet_name="小黄",
        visitor_owner_name="Alice",
    )
    requests: list[tuple[str, str]] = []
    confirmed: list[str] = []
    sent_home: list[str] = []
    window.interaction_requested.connect(
        lambda visit_id, action: requests.append((visit_id, action))
    )
    window.guest_interacted.connect(confirmed.append)
    window.send_guest_home_requested.connect(sent_home.append)

    window.set_interactions_enabled(False)
    assert window.request_interaction("greet") is False
    assert requests == []

    window.set_interactions_enabled(True)
    assert window.request_interaction("greet") is True
    assert requests == [("visit-123", "greet")]
    assert confirmed == []

    window.show_interaction("greet")
    assert confirmed == ["greet"]
    assert "高兴" in window.speech_bubble.text()

    assert window.set_asset_manifest(None) is False
    window.send_guest_home_requested.emit(window.visit_id)
    assert sent_home == ["visit-123"]
    window.close()


def test_away_indicator_displays_countdown_and_recall(qapp) -> None:
    indicator = AwayIndicator(
        visit_id="visit-789",
        pet_name="小白",
        host_name="Bob",
        note="去作客半小时",
        scheduled_end_at=datetime.now(UTC) + timedelta(seconds=75),
    )
    recalled: list[str] = []
    indicator.recall_requested.connect(recalled.append)
    assert indicator.visit_id == "visit-789"
    assert "接待：Bob" in indicator.detail_label.text()
    assert "返家" in indicator.detail_label.text()
    indicator.recall_requested.emit(indicator.visit_id)
    assert recalled == ["visit-789"]
    indicator.close()


def test_dual_pet_scene_prefers_right_then_clamps_to_screen(qapp, monkeypatch) -> None:
    host = QWidget()
    guest = QWidget()
    indicator = QWidget()
    host.resize(100, 120)
    guest.resize(80, 90)
    indicator.resize(120, 50)
    host.move(100, 100)
    coordinator = DualPetSceneCoordinator(normal_gap=10, interaction_gap=2)
    monkeypatch.setattr(
        coordinator,
        "_available_geometry",
        lambda _host: QRect(0, 0, 400, 300),
    )

    normal = coordinator.guest_position(host, guest)
    close = coordinator.guest_position(host, guest, close_interaction=True)
    assert normal.x() == host.frameGeometry().right() + 11
    assert close.x() == host.frameGeometry().right() + 3

    host.move(350, 250)
    left = coordinator.guest_position(host, guest)
    assert left.x() < host.x()
    assert 0 <= left.y() <= 210

    point = coordinator.place_indicator(host, indicator)
    assert 0 <= point.x() <= 280
    assert 0 <= point.y() <= 250

    host.close()
    guest.close()
    indicator.close()
