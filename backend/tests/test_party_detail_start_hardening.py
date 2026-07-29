from __future__ import annotations

from fastapi.testclient import TestClient

from .test_pet_parties import (
    _accept,
    _create_party,
    _create_pet,
    _friend,
    _invite,
    _presence,
    _register,
)


def _account_id(client: TestClient, auth: dict[str, str]) -> str:
    response = client.get("/api/v1/accounts/me", headers=auth)
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def test_declined_member_history_contains_only_own_invitation_outcome(
    client: TestClient,
) -> None:
    host = _register(client, "detail_declined_host")
    participant = _register(client, "detail_declined_participant")
    declined = _register(client, "detail_declined_member")
    host_id = _account_id(client, host)
    declined_id = _account_id(client, declined)
    host_pet = _create_pet(client, host, "详情脱敏发起宠物")
    participant_pet = _create_pet(client, participant, "详情脱敏参与宠物")
    _friend(client, host, participant, "detail_declined_participant")
    _friend(client, host, declined, "detail_declined_member")

    party = _create_party(client, host, host_pet["pet_id"], max_members=3)
    party_id = party["party_id"]
    _invite(client, host, party_id, "detail_declined_member")
    rejected = client.post(f"/api/v1/parties/{party_id}/decline", headers=declined)
    assert rejected.status_code == 200, rejected.text
    _invite(client, host, party_id, "detail_declined_participant")
    _accept(client, participant, party_id, participant_pet["pet_id"])
    started = client.post(f"/api/v1/parties/{party_id}/start", headers=host)
    assert started.status_code == 200, started.text
    interaction = client.post(
        f"/api/v1/parties/{party_id}/interactions/play_together",
        headers=host,
        json={"idempotency_key": "detail-declined-play"},
    )
    assert interaction.status_code == 200, interaction.text
    ended = client.post(f"/api/v1/parties/{party_id}/end", headers=host)
    assert ended.status_code == 200, ended.text

    response = client.get(f"/api/v1/parties/{party_id}", headers=declined)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert {item["account"]["account_id"] for item in payload["members"]} == {
        host_id,
        declined_id,
    }
    assert [item["kind"] for item in payload["timeline"]] == [
        "created",
        "invited",
        "declined",
    ]
    assert payload["started_at"] is None
    assert payload["scheduled_end_at"] is None
    assert payload["ended_at"] is None
    assert payload["completion_reason"] == ""
    assert payload["can_invite"] is False
    assert payload["can_start"] is False
    assert payload["can_end"] is False
    assert payload["can_interact"] is False


def test_expired_member_history_hides_participants_interactions_and_end(
    client: TestClient,
) -> None:
    host = _register(client, "detail_expired_host")
    participant = _register(client, "detail_expired_participant")
    expired = _register(client, "detail_expired_member")
    host_id = _account_id(client, host)
    expired_id = _account_id(client, expired)
    host_pet = _create_pet(client, host, "失效详情发起宠物")
    participant_pet = _create_pet(client, participant, "失效详情参与宠物")
    _friend(client, host, participant, "detail_expired_participant")
    _friend(client, host, expired, "detail_expired_member")

    party = _create_party(client, host, host_pet["pet_id"], max_members=3)
    party_id = party["party_id"]
    _invite(client, host, party_id, "detail_expired_participant")
    _accept(client, participant, party_id, participant_pet["pet_id"])
    _invite(client, host, party_id, "detail_expired_member")
    started = client.post(f"/api/v1/parties/{party_id}/start", headers=host)
    assert started.status_code == 200, started.text
    interaction = client.post(
        f"/api/v1/parties/{party_id}/interactions/group_photo",
        headers=participant,
        json={"idempotency_key": "detail-expired-photo"},
    )
    assert interaction.status_code == 200, interaction.text
    ended = client.post(f"/api/v1/parties/{party_id}/end", headers=host)
    assert ended.status_code == 200, ended.text

    response = client.get(f"/api/v1/parties/{party_id}", headers=expired)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert {item["account"]["account_id"] for item in payload["members"]} == {
        host_id,
        expired_id,
    }
    assert [item["kind"] for item in payload["timeline"]] == [
        "created",
        "invited",
        "expired",
    ]
    assert payload["timeline"][-1]["title"] == "邀请已失效"
    assert "尚未确认参加" in payload["timeline"][-1]["detail"]
    assert payload["started_at"] is None
    assert payload["ended_at"] is None
    assert payload["completion_reason"] == ""


def test_cancelled_invitation_keeps_only_its_cancellation_result(
    client: TestClient,
) -> None:
    host = _register(client, "detail_cancelled_host")
    invited = _register(client, "detail_cancelled_member")
    host_pet = _create_pet(client, host, "取消详情发起宠物")
    _friend(client, host, invited, "detail_cancelled_member")
    party = _create_party(client, host, host_pet["pet_id"], max_members=2)
    party_id = party["party_id"]
    _invite(client, host, party_id, "detail_cancelled_member")

    cancelled = client.post(f"/api/v1/parties/{party_id}/cancel", headers=host)
    assert cancelled.status_code == 200, cancelled.text
    response = client.get(f"/api/v1/parties/{party_id}", headers=invited)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["kind"] for item in payload["timeline"]] == [
        "created",
        "invited",
        "expired",
        "ended",
    ]
    assert payload["completion_reason"] == "party_cancelled"
    assert payload["ended_at"] is not None
    assert payload["started_at"] is None


def test_start_rejects_guest_whose_friendship_was_removed_after_accepting(
    client: TestClient,
) -> None:
    host = _register(client, "start_friend_host")
    guest = _register(client, "start_friend_guest")
    guest_id = _account_id(client, guest)
    host_pet = _create_pet(client, host, "好友复核发起宠物")
    guest_pet = _create_pet(client, guest, "好友复核参与宠物")
    _friend(client, host, guest, "start_friend_guest")
    party = _create_party(client, host, host_pet["pet_id"], max_members=2)
    party_id = party["party_id"]
    _invite(client, host, party_id, "start_friend_guest")
    _accept(client, guest, party_id, guest_pet["pet_id"])

    removed = client.delete(f"/api/v1/friends/{guest_id}", headers=host)
    assert removed.status_code == 204, removed.text
    started = client.post(f"/api/v1/parties/{party_id}/start", headers=host)

    assert started.status_code == 409, started.text
    assert "好友关系已失效" in started.json()["detail"]
    detail = client.get(f"/api/v1/parties/{party_id}", headers=host)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "open"
    assert _presence(client, host, host_pet["pet_id"]) == "home"
    assert _presence(client, guest, guest_pet["pet_id"]) == "home"


def test_start_rejects_guest_when_either_account_has_blocked_the_other(
    client: TestClient,
) -> None:
    host = _register(client, "start_block_host")
    guest = _register(client, "start_block_guest")
    host_pet = _create_pet(client, host, "屏蔽复核发起宠物")
    guest_pet = _create_pet(client, guest, "屏蔽复核参与宠物")
    _friend(client, host, guest, "start_block_guest")
    party = _create_party(client, host, host_pet["pet_id"], max_members=2)
    party_id = party["party_id"]
    _invite(client, host, party_id, "start_block_guest")
    _accept(client, guest, party_id, guest_pet["pet_id"])

    blocked = client.post(
        "/api/v1/blocks",
        headers=guest,
        json={"username": "start_block_host"},
    )
    assert blocked.status_code == 201, blocked.text
    started = client.post(f"/api/v1/parties/{party_id}/start", headers=host)

    assert started.status_code == 409, started.text
    assert "账户关系已变化" in started.json()["detail"]
    detail = client.get(f"/api/v1/parties/{party_id}", headers=host)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "open"
    assert _presence(client, host, host_pet["pet_id"]) == "home"
    assert _presence(client, guest, guest_pet["pet_id"]) == "home"
