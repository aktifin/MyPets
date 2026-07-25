from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from onepic_desktop_pet.visit_app import guest_profile_from_scene
from onepic_desktop_pet.visit_client import VisitController


class FakeSession(QObject):
    state_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.connected = True


class FakeTransport(QObject):
    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[str, str, str, object]] = []

    def request(self, operation, method, path, *, body=None, query=None) -> None:
        self.requests.append((operation, method, path, body))


def _scene() -> dict:
    return {
        "visit_id": "visit-1",
        "status": "active",
        "requester": {
            "account_id": "visitor-owner",
            "username": "visitor_user",
            "display_name": "访客主人",
        },
        "host": {
            "account_id": "host-owner",
            "username": "host_user",
            "display_name": "接待主人",
        },
        "visitor_pet": {
            "pet_id": "visitor-pet",
            "name": "来访小白",
            "presence": "visiting",
            "growth_stage": "child",
            "growth_level": 3,
            "mood": 80,
            "template_id": "official.onepic.demo",
            "template_version": "1.0.0",
            "identity_version": "2.0.0",
            "asset_version": "3.0.0",
            "personality_type": "playful",
        },
        "host_pet": {
            "pet_id": "host-pet",
            "name": "接待小蓝",
            "presence": "home",
            "growth_stage": "child",
            "growth_level": 2,
            "mood": 90,
            "template_id": "official.onepic.demo",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
            "personality_type": "balanced",
        },
        "note": "一起玩",
        "started_at": "2026-07-25T10:00:00+09:00",
        "scheduled_end_at": "2026-07-25T11:00:00+09:00",
        "can_send_home": True,
        "can_interact": True,
    }


def test_guest_profile_uses_public_scene_asset_identity() -> None:
    profile = guest_profile_from_scene(_scene())
    assert profile is not None
    assert profile.identity.pet_id == "visitor-pet"
    assert profile.identity.primary_owner_account_id == "visitor-owner"
    assert profile.identity.template_id == "official.onepic.demo"
    assert profile.identity.identity_version == "2.0.0"
    assert profile.asset_version == "3.0.0"
    assert profile.personality_type == "playful"
    assert profile.presence.value == "visiting"

    invalid = _scene()
    invalid["visitor_pet"] = {"pet_id": "visitor-pet"}
    assert guest_profile_from_scene(invalid) is None


def test_visit_controller_loads_scene_and_confirms_interactions() -> None:
    transport = FakeTransport()
    controller = VisitController(FakeSession(), object(), transport=transport)
    scenes: list[dict] = []
    interactions: list[tuple[str, str]] = []
    failures: list[str] = []
    controller.scene_changed.connect(scenes.append)
    controller.interaction_succeeded.connect(
        lambda visit_id, action: interactions.append((visit_id, action))
    )
    controller.operation_failed.connect(failures.append)

    assert controller.load_scene("visit-1") is True
    assert transport.requests[-1][:3] == (
        "scene:visit-1",
        "GET",
        "/api/v1/visits/visit-1/scene",
    )
    transport.operation_succeeded.emit("scene:visit-1", _scene())
    assert scenes[-1]["visitor_pet"]["name"] == "来访小白"

    controller.interact_guest("visit-1", "sit_together")
    operation, method, path, body = transport.requests[-1]
    assert operation == "mutation:visit_interaction:sit_together"
    assert method == "POST"
    assert path.endswith("/visits/visit-1/interactions/sit_together")
    assert str(body["idempotency_key"]).startswith("desktop-visit-sit_together-")

    transport.operation_succeeded.emit(
        operation,
        {"visit_id": "visit-1", "action": "sit_together"},
    )
    assert interactions == [("visit-1", "sit_together")]

    controller.interact_guest("visit-1", "unknown")
    assert failures[-1] == "不支持的双宠互动动作"
