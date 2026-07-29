from __future__ import annotations

from fastapi.testclient import TestClient

from .test_party_detail_start_hardening import _account_id
from .test_pet_parties import (
    _accept,
    _create_party,
    _create_pet,
    _friend,
    _invite,
    _register,
)


def test_terminal_invitee_list_summary_is_redacted_before_opening_detail(
    client: TestClient,
) -> None:
    host = _register(client, "list_redaction_host")
    participant = _register(client, "list_redaction_participant")
    declined = _register(client, "list_redaction_declined")
    host_id = _account_id(client, host)
    declined_id = _account_id(client, declined)
    host_pet = _create_pet(client, host, "列表脱敏发起宠物")
    participant_pet = _create_pet(client, participant, "列表脱敏参与宠物")
    _friend(client, host, participant, "list_redaction_participant")
    _friend(client, host, declined, "list_redaction_declined")

    party = _create_party(client, host, host_pet["pet_id"], max_members=3)
    party_id = party["party_id"]
    _invite(client, host, party_id, "list_redaction_declined")
    response = client.post(f"/api/v1/parties/{party_id}/decline", headers=declined)
    assert response.status_code == 200, response.text
    _invite(client, host, party_id, "list_redaction_participant")
    _accept(client, participant, party_id, participant_pet["pet_id"])
    started = client.post(f"/api/v1/parties/{party_id}/start", headers=host)
    assert started.status_code == 200, started.text

    listing = client.get("/api/v1/parties", headers=declined)

    assert listing.status_code == 200, listing.text
    history = next(
        item for item in listing.json()["history"] if item["party_id"] == party_id
    )
    assert {item["account"]["account_id"] for item in history["members"]} == {
        host_id,
        declined_id,
    }
    assert history["started_at"] is None
    assert history["scheduled_end_at"] is None
    assert history["ended_at"] is None
    assert history["completion_reason"] == ""
    assert history["can_interact"] is False
