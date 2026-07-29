"""Narrow party-history visibility and revalidate accepted guests before start.

The compatibility party routes remain the authoritative implementation for normal
participants. These exact-path routes are registered first and only add the customer-
safety checks that require a stricter response or a final relationship validation.
They do not introduce another party lifecycle, role, or persistence model.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .party_api import (
    PartyDetailView,
    PartyListResponse,
    PartyTimelineEntryView,
    PartyView,
    _account,
    _aware,
    _blocked,
    _friendship,
    _party,
    _timeline,
    _view,
    list_parties,
    start_party,
)
from .party_models import PetParty, PetPartyMember
from .party_service import party_members, settle_due_parties
from .security import Principal


party_hardening_router = APIRouter(
    prefix="/api/v1/parties",
    tags=["pet-parties"],
    include_in_schema=False,
)

_RESTRICTED_INVITATION_STATES = {"declined", "expired"}


def _redact_party_view(
    base: PartyView,
    *,
    account_id: str,
    current_status: str,
) -> PartyView:
    """Reduce a terminal invitee's summary to the host and their own invitation."""

    visible_members = [
        item
        for item in base.members
        if item.role == "host" or item.account.account_id == account_id
    ]
    active_capacity = [
        item for item in visible_members if item.status in {"invited", "accepted", "joined"}
    ]
    accepted = [
        item for item in visible_members if item.status in {"accepted", "joined"}
    ]
    joined = [item for item in visible_members if item.status == "joined"]
    cancellation_visible = (
        current_status == "expired"
        and base.completion_reason == "party_cancelled"
    )
    return base.model_copy(
        update={
            "completion_reason": base.completion_reason if cancellation_visible else "",
            "started_at": None,
            "scheduled_end_at": None,
            "ended_at": base.ended_at if cancellation_visible else None,
            "member_count": len(active_capacity),
            "accepted_count": len(accepted),
            "joined_count": len(joined),
            "members": visible_members,
            "can_invite": False,
            "can_start": False,
            "can_cancel": False,
            "can_end": False,
            "can_interact": False,
        }
    )


def _redact_list_item(view: PartyView, principal: Principal) -> PartyView:
    current = next(item for item in view.members if item.is_current_account)
    if current.status not in _RESTRICTED_INVITATION_STATES:
        return view
    return _redact_party_view(
        view,
        account_id=principal.account_id,
        current_status=current.status,
    )


def _restricted_timeline(
    session: Session,
    party: PetParty,
    principal: Principal,
    current: PetPartyMember,
) -> list[PartyTimelineEntryView]:
    """Return only creation and the current account's own invitation outcome."""

    full_timeline = _timeline(session, party, principal)
    allowed_ids = {
        f"party:{party.id}:created",
        f"party-member:{current.id}:invited",
    }
    if current.status == "declined":
        allowed_ids.add(f"party-member:{current.id}:responded")

    entries = [item for item in full_timeline if item.event_id in allowed_ids]
    if current.status == "expired":
        raw_occurred_at = (
            current.responded_at
            or party.started_at
            or party.ended_at
            or current.created_at
        )
        occurred_at = _aware(raw_occurred_at)
        assert occurred_at is not None
        if party.completion_reason == "party_cancelled":
            detail = "聚会在开始前取消，本次邀请已失效。"
        elif party.started_at is not None:
            detail = "聚会开始时你尚未确认参加，本次邀请已失效。"
        else:
            detail = "本次聚会邀请已经失效。"
        entries.append(
            PartyTimelineEntryView(
                event_id=f"party-member:{current.id}:expired",
                kind="expired",
                title="邀请已失效",
                detail=detail,
                occurred_at=occurred_at,
                actor_account_id=current.account_id,
                actor_display_name=_account(session, current.account_id).display_name,
            )
        )
        if party.completion_reason == "party_cancelled":
            cancellation = next(
                (
                    item
                    for item in full_timeline
                    if item.event_id == f"party:{party.id}:ended"
                ),
                None,
            )
            if cancellation is not None:
                entries.append(cancellation)

    entries.sort(key=lambda item: (item.occurred_at, item.event_id))
    return entries


def _restricted_detail(
    session: Session,
    party: PetParty,
    principal: Principal,
    base: PartyView,
    current: PetPartyMember,
) -> PartyDetailView:
    redacted = _redact_party_view(
        base,
        account_id=principal.account_id,
        current_status=current.status,
    )
    return PartyDetailView(
        **redacted.model_dump(),
        timeline=_restricted_timeline(session, party, principal, current),
    )


@party_hardening_router.get("", response_model=PartyListResponse)
def list_parties_hardened(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyListResponse:
    result = list_parties(principal, session)
    return PartyListResponse(
        invitations=[_redact_list_item(item, principal) for item in result.invitations],
        open=[_redact_list_item(item, principal) for item in result.open],
        active=[_redact_list_item(item, principal) for item in result.active],
        history=[_redact_list_item(item, principal) for item in result.history],
    )


@party_hardening_router.get("/{party_id}", response_model=PartyDetailView)
def get_party_hardened(
    party_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyDetailView:
    settle_due_parties(session)
    party = _party(session, party_id)
    current = next(
        (
            item
            for item in party_members(session, party.id)
            if item.account_id == principal.account_id
        ),
        None,
    )
    if current is None:
        raise HTTPException(status_code=403, detail="当前账户不是该聚会参与方")
    base = _view(session, party, principal)
    if current.status in _RESTRICTED_INVITATION_STATES:
        result = _restricted_detail(session, party, principal, base, current)
    else:
        result = PartyDetailView(
            **base.model_dump(),
            timeline=_timeline(session, party, principal),
        )
    session.commit()
    return result


@party_hardening_router.post("/{party_id}/start", response_model=PartyView)
def start_party_hardened(
    party_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyView:
    settle_due_parties(session)
    party = _party(session, party_id)
    if party.host_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有聚会发起人可以开始聚会")
    if party.status != "open":
        raise HTTPException(status_code=409, detail="该聚会当前不能开始")

    accepted = [
        item
        for item in party_members(session, party.id)
        if item.status == "accepted" and item.pet_id
    ]
    if len(accepted) < 2:
        raise HTTPException(status_code=409, detail="至少需要两只已确认宠物才能开始聚会")

    for member in accepted:
        if member.role == "host":
            continue
        account = _account(session, member.account_id)
        if _blocked(session, party.host_account_id, member.account_id):
            raise HTTPException(
                status_code=409,
                detail=f"{account.display_name} 与发起人的账户关系已变化，不能开始聚会",
            )
        if _friendship(session, party.host_account_id, member.account_id) is None:
            raise HTTPException(
                status_code=409,
                detail=f"{account.display_name} 与发起人的好友关系已失效，不能开始聚会",
            )

    return start_party(party_id, principal, session)
