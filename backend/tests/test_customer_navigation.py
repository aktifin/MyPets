from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from mypets_backend.models import (
    Account,
    AccountPetRelation,
    Conversation,
    ConversationMember,
    Message,
    Pet,
    SyncEvent,
)
from mypets_backend.visit_models import PetVisit

from .conftest import register_account


def _account_id(client: TestClient, username: str) -> str:
    with client.app.state.session_factory() as session:
        value = session.scalar(select(Account).where(Account.username == username))
        assert value is not None
        return value.id


def _seed_customer_navigation(client: TestClient) -> dict[str, str]:
    requester_auth = register_account(client, "timeline_requester", display_name="来访主人")
    host_auth = register_account(client, "timeline_host", display_name="接待主人")
    outsider_auth = register_account(client, "timeline_outsider", display_name="无关用户")
    requester_id = _account_id(client, "timeline_requester")
    host_id = _account_id(client, "timeline_host")
    outsider_id = _account_id(client, "timeline_outsider")
    now = datetime.now(UTC)
    visitor_id = str(uuid4())
    host_pet_id = str(uuid4())
    visit_id = str(uuid4())
    interaction_id = str(uuid4())
    visit_conversation_id = str(uuid4())
    friend_conversation_id = str(uuid4())

    with client.app.state.session_factory() as session:
        session.add_all(
            [
                Pet(
                    id=visitor_id,
                    name="小白",
                    template_id="official.cat.white",
                    template_version="1.0.0",
                    identity_version="1.0.0",
                    primary_owner_account_id=requester_id,
                    asset_version="1.0.0",
                    presence="home",
                ),
                Pet(
                    id=host_pet_id,
                    name="团子",
                    template_id="official.cat.orange",
                    template_version="1.0.0",
                    identity_version="1.0.0",
                    primary_owner_account_id=host_id,
                    asset_version="1.0.0",
                    presence="home",
                ),
            ]
        )
        session.add_all(
            [
                AccountPetRelation(
                    account_id=requester_id,
                    pet_id=visitor_id,
                    role="owner",
                ),
                AccountPetRelation(
                    account_id=host_id,
                    pet_id=host_pet_id,
                    role="owner",
                ),
            ]
        )
        session.add(
            PetVisit(
                id=visit_id,
                requester_account_id=requester_id,
                host_account_id=host_id,
                visitor_pet_id=visitor_id,
                host_pet_id=host_pet_id,
                status="completed",
                note="周末一起玩",
                duration_minutes=60,
                completion_reason="visit_auto_returned",
                created_at=now - timedelta(hours=2),
                responded_at=now - timedelta(hours=1, minutes=55),
                started_at=now - timedelta(hours=1, minutes=55),
                scheduled_end_at=now - timedelta(minutes=55),
                completed_at=now - timedelta(minutes=55),
            )
        )
        interaction_payload = {
            "cause": "visit_desktop_interaction",
            "interaction": {
                "interaction_id": interaction_id,
                "visit_id": visit_id,
                "action": "play",
                "actor_account_id": host_id,
                "visitor_pet_id": visitor_id,
                "host_pet_id": host_pet_id,
                "created_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
            },
        }
        session.add(
            SyncEvent(
                event_id=str(uuid4()),
                account_id=requester_id,
                event_type="pet_visit_interaction",
                idempotency_key=f"timeline-interaction:{interaction_id}",
                payload_json=json.dumps(interaction_payload),
                created_at=now - timedelta(hours=1, minutes=30),
            )
        )
        session.add_all(
            [
                Conversation(
                    id=visit_conversation_id,
                    kind="direct",
                    direct_key="|".join(sorted((requester_id, host_id))),
                    created_by_account_id=requester_id,
                    created_at=now,
                    updated_at=now,
                ),
                ConversationMember(
                    conversation_id=visit_conversation_id,
                    account_id=requester_id,
                    joined_at=now,
                ),
                ConversationMember(
                    conversation_id=visit_conversation_id,
                    account_id=host_id,
                    joined_at=now,
                ),
                Message(
                    id=str(uuid4()),
                    conversation_id=visit_conversation_id,
                    sender_account_id=requester_id,
                    sender_pet_id=visitor_id,
                    message_type="visit_message",
                    content="周末一起玩",
                    created_at=now,
                ),
                Conversation(
                    id=friend_conversation_id,
                    kind="direct",
                    direct_key="|".join(sorted((requester_id, outsider_id))),
                    created_by_account_id=requester_id,
                    created_at=now,
                    updated_at=now,
                ),
                ConversationMember(
                    conversation_id=friend_conversation_id,
                    account_id=requester_id,
                    joined_at=now,
                ),
                ConversationMember(
                    conversation_id=friend_conversation_id,
                    account_id=outsider_id,
                    joined_at=now,
                ),
                Message(
                    id=str(uuid4()),
                    conversation_id=friend_conversation_id,
                    sender_account_id=requester_id,
                    sender_pet_id=None,
                    message_type="text",
                    content="你好",
                    created_at=now,
                ),
            ]
        )
        session.commit()

    return {
        "requester_auth": requester_auth,
        "host_auth": host_auth,
        "outsider_auth": outsider_auth,
        "requester_id": requester_id,
        "host_id": host_id,
        "visitor_id": visitor_id,
        "host_pet_id": host_pet_id,
        "visit_id": visit_id,
        "visit_conversation_id": visit_conversation_id,
        "friend_conversation_id": friend_conversation_id,
    }


def test_visit_timeline_projects_lifecycle_and_deduplicated_interaction(client: TestClient) -> None:
    values = _seed_customer_navigation(client)
    response = client.get(
        f"/api/v1/visits/{values['visit_id']}/timeline",
        headers=values["requester_auth"],
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["visitor_pet_name"] == "小白"
    assert payload["host_pet_name"] == "团子"
    kinds = [item["kind"] for item in payload["entries"]]
    assert kinds == ["requested", "accepted", "arrived", "interaction", "returned"]
    assert sum(item["kind"] == "interaction" for item in payload["entries"]) == 1
    interaction = next(item for item in payload["entries"] if item["kind"] == "interaction")
    assert interaction["interaction_action"] == "play"
    assert interaction["actor_display_name"] == "接待主人"
    assert "一起玩" in interaction["title"]

    host_view = client.get(
        f"/api/v1/visits/{values['visit_id']}/timeline",
        headers=values["host_auth"],
    )
    assert host_view.status_code == 200
    assert [item["kind"] for item in host_view.json()["entries"]] == [
        "requested",
        "accepted",
        "arrived",
        "returned",
    ]

    forbidden = client.get(
        f"/api/v1/visits/{values['visit_id']}/timeline",
        headers=values["outsider_auth"],
    )
    assert forbidden.status_code == 403


def test_conversation_target_selects_visit_then_friend_fallback(client: TestClient) -> None:
    values = _seed_customer_navigation(client)
    visit_target = client.get(
        f"/api/v1/conversations/{values['visit_conversation_id']}/target",
        headers=values["requester_auth"],
    )
    assert visit_target.status_code == 200, visit_target.text
    assert visit_target.json() == {
        "conversation_id": values["visit_conversation_id"],
        "kind": "visit",
        "target_id": values["visit_id"],
        "label": "查看 小白 → 团子 的串门",
    }

    friend_target = client.get(
        f"/api/v1/conversations/{values['friend_conversation_id']}/target",
        headers=values["requester_auth"],
    )
    assert friend_target.status_code == 200
    assert friend_target.json()["kind"] == "friend"
    assert friend_target.json()["label"] == "查看好友 无关用户"

    forbidden = client.get(
        f"/api/v1/conversations/{values['visit_conversation_id']}/target",
        headers=values["outsider_auth"],
    )
    assert forbidden.status_code == 404
