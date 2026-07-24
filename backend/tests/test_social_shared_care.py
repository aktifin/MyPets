from __future__ import annotations

from fastapi.testclient import TestClient


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": username.title(),
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_pet(client: TestClient, auth: dict[str, str], name: str = "小云") -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": f"create-pet-{name}"},
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


def _friend(client: TestClient, sender: dict[str, str], recipient: dict[str, str], username: str) -> dict:
    sent = client.post(
        "/api/v1/friend-requests",
        headers=sender,
        json={"username": username},
    )
    assert sent.status_code == 201, sent.text
    accepted = client.post(
        f"/api/v1/friend-requests/{sent.json()['request_id']}/accept",
        headers=recipient,
    )
    assert accepted.status_code == 200, accepted.text
    return accepted.json()


def test_friendship_visibility_invitation_and_remote_care_policy(client: TestClient) -> None:
    alice = _register(client, "alice_owner")
    bob = _register(client, "bob_helper")
    charlie = _register(client, "charlie_viewer")

    request = client.post(
        "/api/v1/friend-requests",
        headers=alice,
        json={"username": "bob_helper"},
    )
    assert request.status_code == 201, request.text
    duplicate = client.post(
        "/api/v1/friend-requests",
        headers=bob,
        json={"username": "alice_owner"},
    )
    assert duplicate.status_code == 409

    incoming = client.get("/api/v1/friend-requests", headers=bob)
    assert incoming.status_code == 200
    assert incoming.json()["incoming"][0]["sender"]["username"] == "alice_owner"

    accepted = client.post(
        f"/api/v1/friend-requests/{request.json()['request_id']}/accept",
        headers=bob,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert client.get("/api/v1/friends", headers=alice).json()[0]["friend"]["username"] == "bob_helper"
    assert client.get("/api/v1/friends", headers=bob).json()[0]["friend"]["username"] == "alice_owner"

    pet = _create_pet(client, alice)
    pet_id = pet["pet_id"]

    hidden = client.get(f"/api/v1/friends/{accepted.json()['sender']['account_id']}/pets", headers=bob)
    assert hidden.status_code == 200
    assert hidden.json() == []

    privacy = client.patch(
        f"/api/v1/pets/{pet_id}/privacy",
        headers=alice,
        json={"visibility": "friends", "allow_remote_care": False},
    )
    assert privacy.status_code == 200, privacy.text
    assert privacy.json()["visibility"] == "friends"

    visible = client.get(
        f"/api/v1/friends/{accepted.json()['sender']['account_id']}/pets",
        headers=bob,
    )
    assert visible.status_code == 200
    assert visible.json()[0]["pet_id"] == pet_id
    assert visible.json()[0]["relation_role"] is None

    not_friend_invite = client.post(
        f"/api/v1/pets/{pet_id}/caregiver-invitations",
        headers=alice,
        json={"username": "charlie_viewer", "role": "viewer"},
    )
    assert not_friend_invite.status_code == 409

    invitation = client.post(
        f"/api/v1/pets/{pet_id}/caregiver-invitations",
        headers=alice,
        json={"username": "bob_helper", "role": "caregiver"},
    )
    assert invitation.status_code == 201, invitation.text
    received = client.get("/api/v1/caregiver-invitations", headers=bob)
    assert received.status_code == 200
    assert received.json()["incoming"][0]["pet"]["pet_id"] == pet_id

    accepted_invite = client.post(
        f"/api/v1/caregiver-invitations/{invitation.json()['invitation_id']}/accept",
        headers=bob,
    )
    assert accepted_invite.status_code == 200, accepted_invite.text
    assert accepted_invite.json()["status"] == "accepted"
    assert client.get("/api/v1/pets", headers=bob).json()[0]["pet_id"] == pet_id

    blocked_remote = client.post(
        f"/api/v1/pets/{pet_id}/interactions/feed",
        headers={**bob, "Idempotency-Key": "bob-feed-disabled-001"},
        json={},
    )
    assert blocked_remote.status_code == 403
    assert "远程照料" in blocked_remote.json()["detail"]

    enabled = client.patch(
        f"/api/v1/pets/{pet_id}/privacy",
        headers=alice,
        json={"visibility": "caregivers", "allow_remote_care": True},
    )
    assert enabled.status_code == 200, enabled.text
    cared = client.post(
        f"/api/v1/pets/{pet_id}/interactions/feed",
        headers={**bob, "Idempotency-Key": "bob-feed-enabled-001"},
        json={},
    )
    assert cared.status_code == 200, cared.text
    assert cared.json()["interaction"]["actor_role"] == "caregiver"

    caregivers = client.get(f"/api/v1/pets/{pet_id}/caregivers", headers=alice)
    assert caregivers.status_code == 200
    assert caregivers.json()[0]["account"]["username"] == "bob_helper"
    assert caregivers.json()[0]["relation"]["care_contribution"] > 0

    events = client.get("/api/v1/sync/events?after_sequence=0&limit=500", headers=bob)
    assert events.status_code == 403  # account tokens cannot read the device event stream

    _ = charlie


def test_block_revokes_friendship_pending_invites_and_shared_pet_access(client: TestClient) -> None:
    owner = _register(client, "owner_block")
    helper = _register(client, "helper_block")
    _friend(client, owner, helper, "helper_block")
    pet = _create_pet(client, owner, "小雪")
    pet_id = pet["pet_id"]
    client.patch(
        f"/api/v1/pets/{pet_id}/privacy",
        headers=owner,
        json={"visibility": "friends", "allow_remote_care": True},
    )
    invitation = client.post(
        f"/api/v1/pets/{pet_id}/caregiver-invitations",
        headers=owner,
        json={"username": "helper_block", "role": "caregiver"},
    )
    assert invitation.status_code == 201
    accepted = client.post(
        f"/api/v1/caregiver-invitations/{invitation.json()['invitation_id']}/accept",
        headers=helper,
    )
    assert accepted.status_code == 200

    blocked = client.post(
        "/api/v1/blocks",
        headers=owner,
        json={"username": "helper_block"},
    )
    assert blocked.status_code == 201, blocked.text
    assert client.get("/api/v1/friends", headers=owner).json() == []
    assert client.get("/api/v1/pets", headers=helper).json() == []

    care = client.post(
        f"/api/v1/pets/{pet_id}/interactions/play",
        headers={**helper, "Idempotency-Key": "blocked-helper-play-001"},
        json={},
    )
    assert care.status_code == 404

    forbidden = client.post(
        "/api/v1/friend-requests",
        headers=helper,
        json={"username": "owner_block"},
    )
    assert forbidden.status_code == 403

    blocks = client.get("/api/v1/blocks", headers=owner)
    assert blocks.status_code == 200
    assert blocks.json()[0]["account"]["username"] == "helper_block"
    unblocked = client.delete(
        f"/api/v1/blocks/{blocked.json()['account']['account_id']}",
        headers=owner,
    )
    assert unblocked.status_code == 204
    resent = client.post(
        "/api/v1/friend-requests",
        headers=helper,
        json={"username": "owner_block"},
    )
    assert resent.status_code == 201, resent.text


def test_permissions_and_self_service_shared_care_removal(client: TestClient) -> None:
    owner = _register(client, "owner_permissions")
    helper = _register(client, "helper_permissions")
    stranger = _register(client, "stranger_permissions")
    _friend(client, owner, helper, "helper_permissions")
    pet = _create_pet(client, owner, "小竹")
    pet_id = pet["pet_id"]

    stranger_privacy = client.patch(
        f"/api/v1/pets/{pet_id}/privacy",
        headers=stranger,
        json={"visibility": "public", "allow_remote_care": True},
    )
    assert stranger_privacy.status_code == 404

    invite = client.post(
        f"/api/v1/pets/{pet_id}/caregiver-invitations",
        headers=owner,
        json={"username": "helper_permissions", "role": "viewer"},
    )
    assert invite.status_code == 201
    accepted = client.post(
        f"/api/v1/caregiver-invitations/{invite.json()['invitation_id']}/accept",
        headers=helper,
    )
    assert accepted.status_code == 200

    viewer_care = client.post(
        f"/api/v1/pets/{pet_id}/interactions/pet",
        headers={**helper, "Idempotency-Key": "viewer-care-denied-001"},
        json={},
    )
    assert viewer_care.status_code == 403

    account_id = client.get("/api/v1/accounts/me", headers=helper).json()["id"]
    leave = client.delete(
        f"/api/v1/pets/{pet_id}/caregivers/{account_id}",
        headers=helper,
    )
    assert leave.status_code == 204
    assert client.get("/api/v1/pets", headers=helper).json() == []
