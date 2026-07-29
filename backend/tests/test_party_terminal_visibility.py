from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import bind_device, register_account


def _account_id(client: TestClient, auth: dict[str, str]) -> str:
    response = client.get("/api/v1/accounts/me", headers=auth)
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _create_pet(
    client: TestClient,
    auth: dict[str, str],
    *,
    name: str,
    key: str,
) -> str:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": key},
        json={
            "name": name,
            "template_id": "official.cat.white",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["pet_id"])


def _make_friends(
    client: TestClient,
    host_auth: dict[str, str],
    guest_auth: dict[str, str],
    *,
    guest_username: str,
) -> None:
    created = client.post(
        "/api/v1/friend-requests",
        headers=host_auth,
        json={"username": guest_username},
    )
    assert created.status_code == 201, created.text
    accepted = client.post(
        f"/api/v1/friend-requests/{created.json()['request_id']}/accept",
        headers=guest_auth,
    )
    assert accepted.status_code == 200, accepted.text


def _create_party(client: TestClient, host_auth: dict[str, str], host_pet_id: str) -> str:
    response = client.post(
        "/api/v1/parties",
        headers=host_auth,
        json={
            "host_pet_id": host_pet_id,
            "title": "终态可见性测试聚会",
            "note": "只向仍有参与关系的账户推送后续动态",
            "max_members": 4,
            "duration_minutes": 60,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["party_id"])


def _invite(
    client: TestClient,
    host_auth: dict[str, str],
    party_id: str,
    username: str,
) -> None:
    response = client.post(
        f"/api/v1/parties/{party_id}/invitations",
        headers=host_auth,
        json={"username": username},
    )
    assert response.status_code == 200, response.text


def _events(
    client: TestClient,
    device_auth: dict[str, str],
    *,
    after: int = 0,
) -> dict[str, object]:
    response = client.get(
        f"/api/v1/sync/events?after_sequence={after}&limit=500",
        headers=device_auth,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _party_events(payload: dict[str, object], party_id: str) -> list[dict[str, object]]:
    events = payload.get("events")
    assert isinstance(events, list)
    values: list[dict[str, object]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        body = event.get("payload")
        if not isinstance(body, dict):
            continue
        party = body.get("party")
        interaction = body.get("interaction")
        event_party_id = ""
        if isinstance(party, dict):
            event_party_id = str(party.get("party_id") or "")
        elif isinstance(interaction, dict):
            event_party_id = str(interaction.get("party_id") or "")
        if event_party_id == party_id:
            values.append(event)
    return values


def test_declined_invitee_gets_redacted_terminal_notice_and_no_later_updates(
    client: TestClient,
) -> None:
    host_auth = register_account(client, "visibility_host_one", display_name="聚会发起人")
    active_auth = register_account(client, "visibility_active_one", display_name="正式参与者")
    declined_auth = register_account(client, "visibility_declined", display_name="谢绝邀请者")
    _make_friends(
        client,
        host_auth,
        active_auth,
        guest_username="visibility_active_one",
    )
    _make_friends(
        client,
        host_auth,
        declined_auth,
        guest_username="visibility_declined",
    )
    host_id = _account_id(client, host_auth)
    declined_id = _account_id(client, declined_auth)
    host_pet_id = _create_pet(
        client,
        host_auth,
        name="奶盖",
        key="visibility-host-pet-one",
    )
    active_pet_id = _create_pet(
        client,
        active_auth,
        name="团子",
        key="visibility-active-pet-one",
    )
    _device, declined_device_auth, _secret = bind_device(
        client,
        declined_auth,
        public_id="party-visibility-declined-device",
    )
    baseline = int(_events(client, declined_device_auth)["next_cursor"])

    party_id = _create_party(client, host_auth, host_pet_id)
    _invite(client, host_auth, party_id, "visibility_declined")
    invite_cursor = int(_events(client, declined_device_auth, after=baseline)["next_cursor"])

    declined = client.post(
        f"/api/v1/parties/{party_id}/decline",
        headers=declined_auth,
    )
    assert declined.status_code == 200, declined.text
    terminal_payload = _events(client, declined_device_auth, after=invite_cursor)
    terminal_events = _party_events(terminal_payload, party_id)
    assert len(terminal_events) == 1
    terminal_party = terminal_events[0]["payload"]["party"]
    assert terminal_party["cause"].startswith("party_declined:")
    assert terminal_party["visibility"] == "invitation_record"
    assert {item["account_id"] for item in terminal_party["members"]} == {
        host_id,
        declined_id,
    }
    terminal_cursor = int(terminal_payload["next_cursor"])

    _invite(client, host_auth, party_id, "visibility_active_one")
    accepted = client.post(
        f"/api/v1/parties/{party_id}/accept",
        headers=active_auth,
        json={"pet_id": active_pet_id},
    )
    assert accepted.status_code == 200, accepted.text
    started = client.post(f"/api/v1/parties/{party_id}/start", headers=host_auth)
    assert started.status_code == 200, started.text
    interaction = client.post(
        f"/api/v1/parties/{party_id}/interactions/play_together",
        headers=host_auth,
        json={"idempotency_key": "visibility-declined-play"},
    )
    assert interaction.status_code == 200, interaction.text
    ended = client.post(f"/api/v1/parties/{party_id}/end", headers=host_auth)
    assert ended.status_code == 200, ended.text

    later = _party_events(
        _events(client, declined_device_auth, after=terminal_cursor),
        party_id,
    )
    assert later == []


def test_expired_invitee_gets_one_redacted_expiry_notice_while_participants_continue(
    client: TestClient,
) -> None:
    host_auth = register_account(client, "visibility_host_two", display_name="第二位发起人")
    active_auth = register_account(client, "visibility_active_two", display_name="第二位参与者")
    expired_auth = register_account(client, "visibility_expired", display_name="未响应邀请者")
    _make_friends(
        client,
        host_auth,
        active_auth,
        guest_username="visibility_active_two",
    )
    _make_friends(
        client,
        host_auth,
        expired_auth,
        guest_username="visibility_expired",
    )
    host_id = _account_id(client, host_auth)
    active_id = _account_id(client, active_auth)
    expired_id = _account_id(client, expired_auth)
    host_pet_id = _create_pet(
        client,
        host_auth,
        name="布丁",
        key="visibility-host-pet-two",
    )
    active_pet_id = _create_pet(
        client,
        active_auth,
        name="豆包",
        key="visibility-active-pet-two",
    )
    _device, active_device_auth, _secret = bind_device(
        client,
        active_auth,
        public_id="party-visibility-active-device",
    )
    _device, expired_device_auth, _secret = bind_device(
        client,
        expired_auth,
        public_id="party-visibility-expired-device",
    )

    party_id = _create_party(client, host_auth, host_pet_id)
    _invite(client, host_auth, party_id, "visibility_active_two")
    accepted = client.post(
        f"/api/v1/parties/{party_id}/accept",
        headers=active_auth,
        json={"pet_id": active_pet_id},
    )
    assert accepted.status_code == 200, accepted.text
    _invite(client, host_auth, party_id, "visibility_expired")
    expired_before_start = int(_events(client, expired_device_auth)["next_cursor"])

    started = client.post(f"/api/v1/parties/{party_id}/start", headers=host_auth)
    assert started.status_code == 200, started.text
    expiry_payload = _events(client, expired_device_auth, after=expired_before_start)
    expiry_events = _party_events(expiry_payload, party_id)
    assert len(expiry_events) == 1
    expiry_party = expiry_events[0]["payload"]["party"]
    assert expiry_party["cause"] == "party_started"
    assert expiry_party["visibility"] == "invitation_record"
    assert {item["account_id"] for item in expiry_party["members"]} == {
        host_id,
        expired_id,
    }
    assert active_id not in {item["account_id"] for item in expiry_party["members"]}
    expired_after_start = int(expiry_payload["next_cursor"])
    active_after_start = int(_events(client, active_device_auth)["next_cursor"])

    interaction = client.post(
        f"/api/v1/parties/{party_id}/interactions/group_photo",
        headers=host_auth,
        json={"idempotency_key": "visibility-expired-photo"},
    )
    assert interaction.status_code == 200, interaction.text
    ended = client.post(f"/api/v1/parties/{party_id}/end", headers=host_auth)
    assert ended.status_code == 200, ended.text

    expired_later = _party_events(
        _events(client, expired_device_auth, after=expired_after_start),
        party_id,
    )
    assert expired_later == []

    active_later = _party_events(
        _events(client, active_device_auth, after=active_after_start),
        party_id,
    )
    assert [event["event_type"] for event in active_later] == [
        "pet_party_interaction",
        "pet_party_updated",
    ]
    assert active_later[-1]["payload"]["party"]["cause"] == "party_host_ended"
    assert active_later[-1]["payload"]["party"]["visibility"] == "participant"
