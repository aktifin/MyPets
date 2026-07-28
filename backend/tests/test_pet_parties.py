from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi.testclient import TestClient
from sqlalchemy import select

from mypets_backend.models import AccountPetRelation, SyncEvent
from mypets_backend.party_models import PetParty


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": username.replace("_", " ").title(),
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_pet(client: TestClient, auth: dict[str, str], name: str) -> dict:
    key = sha256(name.encode("utf-8")).hexdigest()[:20]
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": f"party-pet-{key}"},
        json={
            "name": name,
            "template_id": "official.cat.white",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _friend(
    client: TestClient,
    sender: dict[str, str],
    recipient: dict[str, str],
    recipient_username: str,
) -> None:
    request = client.post(
        "/api/v1/friend-requests",
        headers=sender,
        json={"username": recipient_username},
    )
    assert request.status_code == 201, request.text
    accepted = client.post(
        f"/api/v1/friend-requests/{request.json()['request_id']}/accept",
        headers=recipient,
    )
    assert accepted.status_code == 200, accepted.text


def _create_party(
    client: TestClient,
    auth: dict[str, str],
    pet_id: str,
    *,
    max_members: int = 4,
    duration_minutes: int = 60,
) -> dict:
    response = client.post(
        "/api/v1/parties",
        headers=auth,
        json={
            "host_pet_id": pet_id,
            "title": "周末宠物小聚会",
            "note": "只进行轻量互动",
            "max_members": max_members,
            "duration_minutes": duration_minutes,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _invite(
    client: TestClient,
    auth: dict[str, str],
    party_id: str,
    username: str,
) -> dict:
    response = client.post(
        f"/api/v1/parties/{party_id}/invitations",
        headers=auth,
        json={"username": username},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _accept(
    client: TestClient,
    auth: dict[str, str],
    party_id: str,
    pet_id: str,
) -> dict:
    response = client.post(
        f"/api/v1/parties/{party_id}/accept",
        headers=auth,
        json={"pet_id": pet_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _presence(client: TestClient, auth: dict[str, str], pet_id: str) -> str:
    items = client.get("/api/v1/pets", headers=auth).json()
    return next(item["presence"] for item in items if item["pet_id"] == pet_id)


def test_party_mvp_lifecycle_keeps_desktop_and_permission_boundaries(client: TestClient) -> None:
    host = _register(client, "party_host")
    guest_one = _register(client, "party_guest_one")
    guest_two = _register(client, "party_guest_two")
    guest_three = _register(client, "party_guest_three")
    outsider = _register(client, "party_outsider")

    host_pet = _create_pet(client, host, "聚会发起宠物")
    pet_one = _create_pet(client, guest_one, "聚会成员一")
    pet_two = _create_pet(client, guest_two, "聚会成员二")
    pet_three = _create_pet(client, guest_three, "聚会成员三")

    for auth, username in (
        (guest_one, "party_guest_one"),
        (guest_two, "party_guest_two"),
        (guest_three, "party_guest_three"),
    ):
        _friend(client, host, auth, username)

    party = _create_party(client, host, host_pet["pet_id"])
    party_id = party["party_id"]
    assert party["desktop_window_limit"] == 2
    assert party["desktop_render_mode"] == "single_scene"
    assert party["accepted_count"] == 1

    not_friend = client.post(
        f"/api/v1/parties/{party_id}/invitations",
        headers=host,
        json={"username": "party_outsider"},
    )
    assert not_friend.status_code == 409

    _invite(client, host, party_id, "party_guest_one")
    _invite(client, host, party_id, "party_guest_two")
    invited = _invite(client, host, party_id, "party_guest_three")
    assert invited["member_count"] == 4
    assert invited["can_invite"] is False

    full = client.post(
        f"/api/v1/parties/{party_id}/invitations",
        headers=host,
        json={"username": "party_outsider"},
    )
    assert full.status_code in {409, 403}

    _accept(client, guest_one, party_id, pet_one["pet_id"])
    _accept(client, guest_two, party_id, pet_two["pet_id"])
    accepted = _accept(client, guest_three, party_id, pet_three["pet_id"])
    assert accepted["accepted_count"] == 4

    outsider_detail = client.get(f"/api/v1/parties/{party_id}", headers=outsider)
    assert outsider_detail.status_code == 403

    started = client.post(f"/api/v1/parties/{party_id}/start", headers=host)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "active"
    assert started.json()["joined_count"] == 4
    assert started.json()["desktop_window_limit"] == 2

    for auth, pet in (
        (host, host_pet),
        (guest_one, pet_one),
        (guest_two, pet_two),
        (guest_three, pet_three),
    ):
        assert _presence(client, auth, pet["pet_id"]) == "gathering"

    care = client.post(
        f"/api/v1/pets/{pet_one['pet_id']}/interactions/play",
        headers={**guest_one, "Idempotency-Key": "party-care-is-blocked"},
        json={},
    )
    assert care.status_code == 409

    interaction_body = {"idempotency_key": "party-group-play-0001"}
    interaction = client.post(
        f"/api/v1/parties/{party_id}/interactions/play_together",
        headers=guest_one,
        json=interaction_body,
    )
    assert interaction.status_code == 200, interaction.text
    assert len(interaction.json()["pet_ids"]) == 4
    duplicate = client.post(
        f"/api/v1/parties/{party_id}/interactions/play_together",
        headers=guest_one,
        json=interaction_body,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["interaction_id"] == interaction.json()["interaction_id"]

    detail = client.get(f"/api/v1/parties/{party_id}", headers=guest_two)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["desktop_window_limit"] == 2
    assert payload["desktop_render_mode"] == "single_scene"
    assert any(item["kind"] == "interaction" for item in payload["timeline"])
    assert any("最多显示两只" in item["detail"] for item in payload["timeline"])

    left = client.post(f"/api/v1/parties/{party_id}/leave", headers=guest_three)
    assert left.status_code == 200, left.text
    assert left.json()["status"] == "active"
    assert _presence(client, guest_three, pet_three["pet_id"]) == "home"

    ended = client.post(f"/api/v1/parties/{party_id}/end", headers=host)
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "completed"
    assert ended.json()["completion_reason"] == "party_host_ended"
    for auth, pet in ((host, host_pet), (guest_one, pet_one), (guest_two, pet_two)):
        assert _presence(client, auth, pet["pet_id"]) == "home"

    with client.app.state.session_factory() as session:
        relations = list(
            session.scalars(
                select(AccountPetRelation).where(
                    AccountPetRelation.pet_id.in_(
                        {
                            host_pet["pet_id"],
                            pet_one["pet_id"],
                            pet_two["pet_id"],
                            pet_three["pet_id"],
                        }
                    )
                )
            )
        )
        assert len(relations) == 4
        assert {item.role for item in relations} == {"owner"}
        events = list(
            session.scalars(
                select(SyncEvent).where(
                    SyncEvent.event_type == "pet_party_interaction"
                )
            )
        )
        assert len(events) == 4


def test_party_decline_capacity_and_lazy_auto_end(client: TestClient) -> None:
    host = _register(client, "party_auto_host")
    guest = _register(client, "party_auto_guest")
    alternate = _register(client, "party_auto_alternate")
    host_pet = _create_pet(client, host, "自动结束发起宠物")
    alternate_pet = _create_pet(client, alternate, "替补宠物")
    _friend(client, host, guest, "party_auto_guest")
    _friend(client, host, alternate, "party_auto_alternate")

    party = _create_party(
        client,
        host,
        host_pet["pet_id"],
        max_members=2,
        duration_minutes=15,
    )
    party_id = party["party_id"]
    _invite(client, host, party_id, "party_auto_guest")
    declined = client.post(f"/api/v1/parties/{party_id}/decline", headers=guest)
    assert declined.status_code == 200
    assert declined.json()["can_invite"] is False
    host_detail = client.get(f"/api/v1/parties/{party_id}", headers=host)
    assert host_detail.status_code == 200
    assert host_detail.json()["can_invite"] is True
    assert host_detail.json()["member_count"] == 1

    _invite(client, host, party_id, "party_auto_alternate")
    _accept(client, alternate, party_id, alternate_pet["pet_id"])
    started = client.post(f"/api/v1/parties/{party_id}/start", headers=host)
    assert started.status_code == 200, started.text
    assert _presence(client, host, host_pet["pet_id"]) == "gathering"
    assert _presence(client, alternate, alternate_pet["pet_id"]) == "gathering"

    with client.app.state.session_factory() as session:
        value = session.get(PetParty, party_id)
        assert value is not None
        value.scheduled_end_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    assert _presence(client, host, host_pet["pet_id"]) == "home"
    detail = client.get(f"/api/v1/parties/{party_id}", headers=host)
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["completion_reason"] == "party_auto_ended"
    assert any(item["title"] == "聚会按时结束" for item in detail.json()["timeline"])

    listing = client.get("/api/v1/parties", headers=alternate)
    assert listing.status_code == 200
    assert any(item["party_id"] == party_id for item in listing.json()["history"])
