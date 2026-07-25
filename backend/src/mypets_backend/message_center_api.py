"""Idempotent domain-event projection into categorized message conversations."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .messaging_api import ConversationView, _conversation_view, publish_typed_message
from .models import Conversation, ConversationMember, Pet, SyncEvent
from .security import Principal
from .visit_models import PetVisit

message_center_router = APIRouter(prefix="/api/v1", tags=["messaging"])
_PROJECTABLE_TYPES = {
    "pet_visit_updated",
    "caregiver_invitation_received",
    "growth_level_up",
    "bond_level_up",
    "growth_stage_changed",
}


def _payload(event: SyncEvent) -> dict[str, Any]:
    try:
        value = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _project_visit(session: Session, payload: dict[str, Any]) -> None:
    visit_data = payload.get("visit")
    if not isinstance(visit_data, dict) or visit_data.get("cause") != "visit_requested":
        return
    visit_id = _string(visit_data.get("visit_id"))
    visit = session.get(PetVisit, visit_id) if visit_id else None
    if visit is None:
        return
    visitor = session.get(Pet, visit.visitor_pet_id)
    host_pet = session.get(Pet, visit.host_pet_id)
    visitor_name = visitor.name if visitor is not None else "好友宠物"
    host_name = host_pet.name if host_pet is not None else "你的宠物"
    content = visit.note.strip() or f"{visitor_name} 想来和 {host_name} 串门。"
    publish_typed_message(
        session,
        sender_account_id=visit.requester_account_id,
        recipient_account_id=visit.host_account_id,
        message_type="visit_message",
        content=content,
        sender_pet_id=visit.visitor_pet_id,
        idempotency_key=f"message-projection:visit:{visit.id}",
    )


def _project_caregiver(session: Session, payload: dict[str, Any]) -> None:
    invitation = payload.get("caregiver_invitation")
    if not isinstance(invitation, dict):
        return
    invitation_id = _string(invitation.get("invitation_id"))
    invited_by = invitation.get("invited_by")
    invited = invitation.get("invited_account")
    pet = invitation.get("pet")
    if not all(isinstance(item, dict) for item in (invited_by, invited, pet)):
        return
    assert isinstance(invited_by, dict)
    assert isinstance(invited, dict)
    assert isinstance(pet, dict)
    sender_account_id = _string(invited_by.get("account_id"))
    recipient_account_id = _string(invited.get("account_id"))
    pet_id = _string(pet.get("pet_id"))
    pet_name = _string(pet.get("name")) or "宠物"
    role = _string(invitation.get("role"))
    role_label = "照料者" if role == "caregiver" else "观察者"
    if not invitation_id or not sender_account_id or not recipient_account_id:
        return
    publish_typed_message(
        session,
        sender_account_id=sender_account_id,
        recipient_account_id=recipient_account_id,
        message_type="care_event",
        content=f"邀请你以{role_label}身份共同照料 {pet_name}。",
        sender_pet_id=pet_id or None,
        idempotency_key=f"message-projection:caregiver:{invitation_id}",
    )


def _project_growth(session: Session, event: SyncEvent, payload: dict[str, Any]) -> None:
    pet_data = payload.get("pet")
    transition = payload.get("transition")
    if not isinstance(pet_data, dict) or not isinstance(transition, dict):
        return
    pet_name = _string(pet_data.get("name")) or "宠物"
    pet_id = _string(pet_data.get("pet_id"))
    previous = _string(transition.get("previous_value"))
    current = _string(transition.get("current_value"))
    label = {
        "growth_level_up": "成长等级提升",
        "bond_level_up": "羁绊等级提升",
        "growth_stage_changed": "成长阶段变化",
    }.get(event.event_type, "成长变化")
    publish_typed_message(
        session,
        sender_account_id=event.account_id,
        recipient_account_id=None,
        message_type="growth_notice",
        content=f"{pet_name}：{label}，{previous} → {current}。",
        sender_pet_id=pet_id or None,
        idempotency_key=f"message-projection:growth:{event.event_id}",
        title="成长通知",
    )


def project_account_messages(session: Session, account_id: str) -> int:
    """Materialize recent domain events once; malformed historical events are ignored."""

    events = list(
        session.scalars(
            select(SyncEvent)
            .where(
                SyncEvent.account_id == account_id,
                SyncEvent.event_type.in_(_PROJECTABLE_TYPES),
            )
            .order_by(SyncEvent.sequence.desc())
            .limit(500)
        )
    )
    before = session.scalar(select(SyncEvent.sequence).order_by(SyncEvent.sequence.desc()).limit(1)) or 0
    for event in reversed(events):
        payload = _payload(event)
        try:
            if event.event_type == "pet_visit_updated":
                _project_visit(session, payload)
            elif event.event_type == "caregiver_invitation_received":
                _project_caregiver(session, payload)
            elif event.event_type in {
                "growth_level_up",
                "bond_level_up",
                "growth_stage_changed",
            }:
                _project_growth(session, event, payload)
        except ValueError:
            continue
    session.flush()
    after = session.scalar(select(SyncEvent.sequence).order_by(SyncEvent.sequence.desc()).limit(1)) or 0
    return max(0, int(after) - int(before))


@message_center_router.get("/conversations", response_model=list[ConversationView])
def list_categorized_conversations(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ConversationView]:
    project_account_messages(session, principal.account_id)
    session.commit()
    conversations = list(
        session.scalars(
            select(Conversation)
            .join(
                ConversationMember,
                ConversationMember.conversation_id == Conversation.id,
            )
            .where(ConversationMember.account_id == principal.account_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .limit(limit)
        )
    )
    return [
        _conversation_view(session, conversation, principal.account_id)
        for conversation in conversations
    ]
