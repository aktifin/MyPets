"""Customer-facing minimal multi-pet party APIs and timeline projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import Account, AccountPetRelation, Pet, SyncEvent
from .party_models import PetParty, PetPartyMember
from .party_service import (
    finish_party,
    has_open_party_for_pet,
    party_members,
    publish_party_pet,
    publish_party_update,
    settle_due_parties,
)
from .security import Principal, normalize_username
from .services import append_event, find_event_by_idempotency
from .social_models import AccountBlock, Friendship
from .visit_models import PetVisit


party_router = APIRouter(prefix="/api/v1/parties", tags=["pet-parties"])

PartyStatus = Literal["open", "active", "completed", "cancelled"]
MemberStatus = Literal["invited", "accepted", "declined", "joined", "left", "completed", "expired"]
PartyInteractionAction = Literal[
    "greet_circle",
    "play_together",
    "group_photo",
    "rest_together",
]

_INTERACTION_LABELS = {
    "greet_circle": ("围成一圈打招呼", "参加聚会的宠物友好地互相打了招呼。"),
    "play_together": ("一起玩耍", "参加聚会的宠物完成了一次集体玩耍。"),
    "group_photo": ("留下合影", "参加聚会的宠物一起留下了一条聚会合影纪念记录。"),
    "rest_together": ("一起休息", "参加聚会的宠物安静地一起休息了一会儿。"),
}


class PartyCreateRequest(BaseModel):
    host_pet_id: str = Field(min_length=1, max_length=36)
    title: str = Field(default="宠物小聚会", min_length=1, max_length=80)
    note: str = Field(default="", max_length=200)
    max_members: int = Field(default=4, ge=2, le=4)
    duration_minutes: int = Field(default=60, ge=15, le=180)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空")
        return stripped

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str) -> str:
        return value.strip()


class PartyInviteRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)

    @field_validator("username")
    @classmethod
    def _normalize_username(cls, value: str) -> str:
        return normalize_username(value)


class PartyAcceptRequest(BaseModel):
    pet_id: str = Field(min_length=1, max_length=36)


class PartyInteractionRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class PartyAccountView(BaseModel):
    account_id: str
    username: str
    display_name: str


class PartyPetView(BaseModel):
    pet_id: str
    name: str
    presence: str
    growth_stage: str
    growth_level: int
    mood: int
    template_id: str
    template_version: str
    identity_version: str
    asset_version: str
    personality_type: str


class PartyMemberView(BaseModel):
    member_id: str
    account: PartyAccountView
    pet: PartyPetView | None
    role: str
    status: MemberStatus
    created_at: datetime
    responded_at: datetime | None
    joined_at: datetime | None
    left_at: datetime | None
    is_current_account: bool
    can_accept: bool
    can_decline: bool
    can_leave: bool


class PartyView(BaseModel):
    party_id: str
    title: str
    note: str
    status: PartyStatus
    host_account_id: str
    host_pet_id: str
    max_members: int
    duration_minutes: int
    completion_reason: str
    created_at: datetime
    started_at: datetime | None
    scheduled_end_at: datetime | None
    ended_at: datetime | None
    member_count: int
    accepted_count: int
    joined_count: int
    members: list[PartyMemberView]
    can_invite: bool
    can_start: bool
    can_cancel: bool
    can_end: bool
    can_interact: bool
    desktop_window_limit: int = 2
    desktop_render_mode: Literal["single_scene"] = "single_scene"


class PartyListResponse(BaseModel):
    invitations: list[PartyView]
    open: list[PartyView]
    active: list[PartyView]
    history: list[PartyView]


class PartyTimelineEntryView(BaseModel):
    event_id: str
    kind: str
    title: str
    detail: str
    occurred_at: datetime
    actor_account_id: str | None = None
    actor_display_name: str | None = None
    action: str | None = None


class PartyDetailView(PartyView):
    timeline: list[PartyTimelineEntryView]


class PartyInteractionView(BaseModel):
    interaction_id: str
    party_id: str
    action: PartyInteractionAction
    actor_account_id: str
    pet_ids: list[str]
    created_at: datetime


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _account(session: Session, account_id: str) -> Account:
    value = session.get(Account, account_id)
    if value is None:
        raise RuntimeError("聚会记录引用了不存在的账户")
    return value


def _account_view(value: Account) -> PartyAccountView:
    return PartyAccountView(
        account_id=value.id,
        username=value.username,
        display_name=value.display_name,
    )


def _pet_view(value: Pet) -> PartyPetView:
    return PartyPetView(
        pet_id=value.id,
        name=value.name,
        presence=value.presence,
        growth_stage=value.growth_stage,
        growth_level=value.growth_level,
        mood=value.mood,
        template_id=value.template_id,
        template_version=value.template_version,
        identity_version=value.identity_version,
        asset_version=value.asset_version,
        personality_type=value.personality_type,
    )


def _party(session: Session, party_id: str) -> PetParty:
    value = session.get(PetParty, party_id)
    if value is None:
        raise HTTPException(status_code=404, detail="宠物聚会不存在")
    return value


def _membership(session: Session, party_id: str, account_id: str) -> PetPartyMember | None:
    return session.scalar(
        select(PetPartyMember).where(
            PetPartyMember.party_id == party_id,
            PetPartyMember.account_id == account_id,
        )
    )


def _require_membership(session: Session, party: PetParty, account_id: str) -> PetPartyMember:
    member = _membership(session, party.id, account_id)
    if member is None:
        raise HTTPException(status_code=403, detail="当前账户不是该聚会参与方")
    return member


def _manager_relation(session: Session, account_id: str, pet_id: str) -> AccountPetRelation | None:
    relation = session.get(AccountPetRelation, (account_id, pet_id))
    return relation if relation is not None and relation.role in {"owner", "co_owner"} else None


def _require_managed_pet(session: Session, account_id: str, pet_id: str) -> Pet:
    pet = session.get(Pet, pet_id)
    if pet is None or _manager_relation(session, account_id, pet_id) is None:
        raise HTTPException(status_code=404, detail="宠物不存在或当前账户无管理权限")
    return pet


def _friendship(session: Session, left: str, right: str) -> Friendship | None:
    low, high = (left, right) if left < right else (right, left)
    return session.scalar(
        select(Friendship).where(
            Friendship.account_low_id == low,
            Friendship.account_high_id == high,
        )
    )


def _blocked(session: Session, left: str, right: str) -> bool:
    return (
        session.get(AccountBlock, (left, right)) is not None
        or session.get(AccountBlock, (right, left)) is not None
    )


def _has_open_visit_for_any_role(session: Session, pet_id: str) -> bool:
    return session.scalar(
        select(PetVisit.id)
        .where(
            PetVisit.status.in_({"pending", "active"}),
            or_(PetVisit.visitor_pet_id == pet_id, PetVisit.host_pet_id == pet_id),
        )
        .limit(1)
    ) is not None


def _ensure_pet_available(
    session: Session,
    pet: Pet,
    *,
    exclude_party_id: str | None = None,
) -> None:
    if pet.presence not in {"home", "resting"}:
        raise HTTPException(status_code=409, detail=f"{pet.name} 当前不在家，不能参加聚会")
    if _has_open_visit_for_any_role(session, pet.id):
        raise HTTPException(status_code=409, detail=f"{pet.name} 已有待处理或进行中的串门")
    if has_open_party_for_pet(session, pet.id, exclude_party_id=exclude_party_id):
        raise HTTPException(status_code=409, detail=f"{pet.name} 已参加其他待开始或进行中的聚会")


def _member_view(
    session: Session,
    party: PetParty,
    member: PetPartyMember,
    principal: Principal,
) -> PartyMemberView:
    account = _account(session, member.account_id)
    pet = session.get(Pet, member.pet_id) if member.pet_id else None
    current = member.account_id == principal.account_id
    return PartyMemberView(
        member_id=member.id,
        account=_account_view(account),
        pet=_pet_view(pet) if pet is not None else None,
        role=member.role,
        status=member.status,  # type: ignore[arg-type]
        created_at=_aware(member.created_at),  # type: ignore[arg-type]
        responded_at=_aware(member.responded_at),
        joined_at=_aware(member.joined_at),
        left_at=_aware(member.left_at),
        is_current_account=current,
        can_accept=current and party.status == "open" and member.status == "invited",
        can_decline=current and party.status == "open" and member.status == "invited",
        can_leave=(
            current
            and party.status == "active"
            and member.status == "joined"
            and member.role != "host"
        ),
    )


def _view(session: Session, party: PetParty, principal: Principal) -> PartyView:
    values = party_members(session, party.id)
    _require_membership(session, party, principal.account_id)
    active_capacity = [
        item for item in values if item.status in {"invited", "accepted", "joined"}
    ]
    accepted = [item for item in values if item.status in {"accepted", "joined"}]
    joined = [item for item in values if item.status == "joined"]
    current = next(item for item in values if item.account_id == principal.account_id)
    is_host = party.host_account_id == principal.account_id
    return PartyView(
        party_id=party.id,
        title=party.title,
        note=party.note,
        status=party.status,  # type: ignore[arg-type]
        host_account_id=party.host_account_id,
        host_pet_id=party.host_pet_id,
        max_members=party.max_members,
        duration_minutes=party.duration_minutes,
        completion_reason=party.completion_reason,
        created_at=_aware(party.created_at),  # type: ignore[arg-type]
        started_at=_aware(party.started_at),
        scheduled_end_at=_aware(party.scheduled_end_at),
        ended_at=_aware(party.ended_at),
        member_count=len(active_capacity),
        accepted_count=len(accepted),
        joined_count=len(joined),
        members=[_member_view(session, party, item, principal) for item in values],
        can_invite=is_host and party.status == "open" and len(active_capacity) < party.max_members,
        can_start=is_host and party.status == "open" and len(accepted) >= 2,
        can_cancel=is_host and party.status == "open",
        can_end=is_host and party.status == "active",
        can_interact=party.status == "active" and current.status == "joined",
    )


def _payload(event: SyncEvent) -> dict[str, object]:
    try:
        value = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _timeline(
    session: Session,
    party: PetParty,
    principal: Principal,
) -> list[PartyTimelineEntryView]:
    values = party_members(session, party.id)
    entries: list[tuple[int, PartyTimelineEntryView]] = []
    host = _account(session, party.host_account_id)
    entries.append(
        (
            10,
            PartyTimelineEntryView(
                event_id=f"party:{party.id}:created",
                kind="created",
                title="聚会已创建",
                detail=f"{host.display_name} 创建了“{party.title}”，最多 {party.max_members} 只宠物参加。",
                occurred_at=_aware(party.created_at),  # type: ignore[arg-type]
                actor_account_id=host.id,
                actor_display_name=host.display_name,
            ),
        )
    )
    for member in values:
        account = _account(session, member.account_id)
        if member.role != "host":
            entries.append(
                (
                    20,
                    PartyTimelineEntryView(
                        event_id=f"party-member:{member.id}:invited",
                        kind="invited",
                        title="已发送邀请",
                        detail=f"已邀请 {account.display_name} 带一只宠物参加聚会。",
                        occurred_at=_aware(member.created_at),  # type: ignore[arg-type]
                        actor_account_id=party.host_account_id,
                        actor_display_name=host.display_name,
                    ),
                )
            )
        if member.responded_at and member.status in {"accepted", "joined", "declined"}:
            pet = session.get(Pet, member.pet_id) if member.pet_id else None
            accepted = member.status in {"accepted", "joined"}
            entries.append(
                (
                    30,
                    PartyTimelineEntryView(
                        event_id=f"party-member:{member.id}:responded",
                        kind="accepted" if accepted else "declined",
                        title="已接受邀请" if accepted else "已谢绝邀请",
                        detail=(
                            f"{account.display_name} 选择 {pet.name if pet else '一只宠物'} 参加聚会。"
                            if accepted
                            else f"{account.display_name} 谢绝了本次聚会邀请。"
                        ),
                        occurred_at=_aware(member.responded_at),  # type: ignore[arg-type]
                        actor_account_id=account.id,
                        actor_display_name=account.display_name,
                    ),
                )
            )
    if party.started_at:
        entries.append(
            (
                40,
                PartyTimelineEntryView(
                    event_id=f"party:{party.id}:started",
                    kind="started",
                    title="聚会正式开始",
                    detail="已接受邀请的宠物进入同一个聚会场景，桌面常驻窗口仍最多显示两只宠物。",
                    occurred_at=_aware(party.started_at),  # type: ignore[arg-type]
                    actor_account_id=host.id,
                    actor_display_name=host.display_name,
                ),
            )
        )

    rows = list(
        session.scalars(
            select(SyncEvent)
            .where(
                SyncEvent.account_id == principal.account_id,
                SyncEvent.event_type == "pet_party_interaction",
            )
            .order_by(SyncEvent.created_at, SyncEvent.sequence)
            .limit(2000)
        )
    )
    seen: set[str] = set()
    for row in rows:
        interaction = _payload(row).get("interaction")
        if not isinstance(interaction, dict):
            continue
        if str(interaction.get("party_id") or "") != party.id:
            continue
        interaction_id = str(interaction.get("interaction_id") or row.event_id)
        if interaction_id in seen:
            continue
        seen.add(interaction_id)
        action = str(interaction.get("action") or "")
        title, detail = _INTERACTION_LABELS.get(
            action,
            ("完成了一次聚会互动", "参加聚会的宠物完成了一次集体互动。"),
        )
        actor_id = str(interaction.get("actor_account_id") or "") or None
        raw_time = interaction.get("created_at")
        try:
            occurred_at = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        except ValueError:
            occurred_at = row.created_at
        actor = session.get(Account, actor_id) if actor_id else None
        entries.append(
            (
                50,
                PartyTimelineEntryView(
                    event_id=f"party-interaction:{interaction_id}",
                    kind="interaction",
                    title=title,
                    detail=detail,
                    occurred_at=_aware(occurred_at),  # type: ignore[arg-type]
                    actor_account_id=actor_id,
                    actor_display_name=actor.display_name if actor else None,
                    action=action or None,
                ),
            )
        )

    for member in values:
        if not member.left_at or member.role == "host":
            continue
        account = _account(session, member.account_id)
        entries.append(
            (
                60,
                PartyTimelineEntryView(
                    event_id=f"party-member:{member.id}:left",
                    kind="left",
                    title="已提前离场",
                    detail=f"{account.display_name} 的宠物已安全离开聚会并返回家中。",
                    occurred_at=_aware(member.left_at),  # type: ignore[arg-type]
                    actor_account_id=account.id,
                    actor_display_name=account.display_name,
                ),
            )
        )
    if party.ended_at:
        labels = {
            "party_auto_ended": ("聚会按时结束", "聚会时间已到，仍在场的宠物已安全返回家中。"),
            "party_host_ended": ("发起人结束聚会", "发起人结束了本次聚会，仍在场的宠物已返回家中。"),
            "party_cancelled": ("聚会已取消", "发起人在开始前取消了本次聚会。"),
            "party_no_longer_has_guests": ("聚会提前结束", "其他宠物均已离场，本次聚会已结束。"),
        }
        title, detail = labels.get(
            party.completion_reason,
            ("聚会已经结束", "本次宠物聚会已经结束。"),
        )
        entries.append(
            (
                70,
                PartyTimelineEntryView(
                    event_id=f"party:{party.id}:ended",
                    kind="ended",
                    title=title,
                    detail=detail,
                    occurred_at=_aware(party.ended_at),  # type: ignore[arg-type]
                    actor_account_id=(
                        party.host_account_id
                        if party.completion_reason in {"party_host_ended", "party_cancelled"}
                        else None
                    ),
                    actor_display_name=(
                        host.display_name
                        if party.completion_reason in {"party_host_ended", "party_cancelled"}
                        else None
                    ),
                ),
            )
        )
    entries.sort(key=lambda item: (item[1].occurred_at, item[0], item[1].event_id))
    return [item for _order, item in entries]


@party_router.post("", response_model=PartyView, status_code=201)
def create_party(
    body: PartyCreateRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyView:
    settle_due_parties(session)
    host_pet = _require_managed_pet(session, principal.account_id, body.host_pet_id)
    _ensure_pet_available(session, host_pet)
    now = datetime.now(UTC)
    party = PetParty(
        id=str(uuid4()),
        host_account_id=principal.account_id,
        host_pet_id=host_pet.id,
        title=body.title,
        note=body.note,
        status="open",
        max_members=body.max_members,
        duration_minutes=body.duration_minutes,
        created_at=now,
    )
    host_member = PetPartyMember(
        id=str(uuid4()),
        party_id=party.id,
        account_id=principal.account_id,
        pet_id=host_pet.id,
        invited_by_account_id=principal.account_id,
        role="host",
        status="accepted",
        created_at=now,
        responded_at=now,
    )
    session.add_all([party, host_member])
    session.flush()
    publish_party_update(session, party, cause="party_created", members=[host_member])
    result = _view(session, party, principal)
    session.commit()
    return result


@party_router.get("", response_model=PartyListResponse)
def list_parties(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyListResponse:
    settle_due_parties(session)
    values = list(
        session.scalars(
            select(PetParty)
            .join(PetPartyMember, PetPartyMember.party_id == PetParty.id)
            .where(PetPartyMember.account_id == principal.account_id)
            .order_by(PetParty.created_at.desc())
            .limit(200)
        )
    )
    viewed = [(item, _view(session, item, principal)) for item in values]
    session.commit()
    return PartyListResponse(
        invitations=[
            view
            for item, view in viewed
            if item.status == "open"
            and next(member for member in view.members if member.is_current_account).status == "invited"
        ],
        open=[
            view
            for item, view in viewed
            if item.status == "open"
            and next(member for member in view.members if member.is_current_account).status != "invited"
        ],
        active=[
            view
            for item, view in viewed
            if item.status == "active"
            and next(member for member in view.members if member.is_current_account).status == "joined"
        ],
        history=[
            view
            for item, view in viewed
            if item.status in {"completed", "cancelled"}
            or next(member for member in view.members if member.is_current_account).status
            in {"declined", "left", "completed", "expired"}
        ][:100],
    )


@party_router.get("/{party_id}", response_model=PartyDetailView)
def get_party(
    party_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyDetailView:
    settle_due_parties(session)
    party = _party(session, party_id)
    base = _view(session, party, principal)
    result = PartyDetailView(**base.model_dump(), timeline=_timeline(session, party, principal))
    session.commit()
    return result


@party_router.post("/{party_id}/invitations", response_model=PartyView)
def invite_to_party(
    party_id: str,
    body: PartyInviteRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyView:
    settle_due_parties(session)
    party = _party(session, party_id)
    if party.host_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有聚会发起人可以邀请成员")
    if party.status != "open":
        raise HTTPException(status_code=409, detail="只有尚未开始的聚会可以继续邀请")
    target = session.scalar(select(Account).where(Account.username == body.username))
    if target is None:
        raise HTTPException(status_code=404, detail="好友账户不存在")
    if target.id == principal.account_id:
        raise HTTPException(status_code=400, detail="发起人已经在聚会中")
    if _blocked(session, principal.account_id, target.id):
        raise HTTPException(status_code=403, detail="当前账户关系不允许发送聚会邀请")
    if _friendship(session, principal.account_id, target.id) is None:
        raise HTTPException(status_code=409, detail="只能邀请好友参加宠物聚会")
    if _membership(session, party.id, target.id) is not None:
        raise HTTPException(status_code=409, detail="该好友已经收到本次聚会邀请")
    active_count = sum(
        item.status in {"invited", "accepted", "joined"}
        for item in party_members(session, party.id)
    )
    if active_count >= party.max_members:
        raise HTTPException(status_code=409, detail="本次聚会邀请名额已满")
    now = datetime.now(UTC)
    member = PetPartyMember(
        id=str(uuid4()),
        party_id=party.id,
        account_id=target.id,
        pet_id=None,
        invited_by_account_id=principal.account_id,
        role="member",
        status="invited",
        created_at=now,
    )
    session.add(member)
    session.flush()
    publish_party_update(session, party, cause=f"party_invited:{member.id}")
    result = _view(session, party, principal)
    session.commit()
    return result


@party_router.post("/{party_id}/accept", response_model=PartyView)
def accept_party_invitation(
    party_id: str,
    body: PartyAcceptRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyView:
    settle_due_parties(session)
    party = _party(session, party_id)
    member = _require_membership(session, party, principal.account_id)
    if party.status != "open" or member.status != "invited":
        raise HTTPException(status_code=409, detail="该聚会邀请当前不能接受")
    if _blocked(session, party.host_account_id, principal.account_id):
        raise HTTPException(status_code=403, detail="当前账户关系不允许参加聚会")
    if _friendship(session, party.host_account_id, principal.account_id) is None:
        raise HTTPException(status_code=409, detail="与发起人的好友关系已失效")
    pet = _require_managed_pet(session, principal.account_id, body.pet_id)
    _ensure_pet_available(session, pet, exclude_party_id=party.id)
    now = datetime.now(UTC)
    member.pet_id = pet.id
    member.status = "accepted"
    member.responded_at = now
    session.flush()
    publish_party_update(session, party, cause=f"party_accepted:{member.id}")
    result = _view(session, party, principal)
    session.commit()
    return result


@party_router.post("/{party_id}/decline", response_model=PartyView)
def decline_party_invitation(
    party_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyView:
    settle_due_parties(session)
    party = _party(session, party_id)
    member = _require_membership(session, party, principal.account_id)
    if party.status != "open" or member.status != "invited":
        raise HTTPException(status_code=409, detail="该聚会邀请当前不能谢绝")
    member.status = "declined"
    member.responded_at = datetime.now(UTC)
    session.flush()
    publish_party_update(session, party, cause=f"party_declined:{member.id}")
    result = _view(session, party, principal)
    session.commit()
    return result


@party_router.post("/{party_id}/start", response_model=PartyView)
def start_party(
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
    values = party_members(session, party.id)
    accepted = [item for item in values if item.status == "accepted" and item.pet_id]
    if len(accepted) < 2:
        raise HTTPException(status_code=409, detail="至少需要两只已确认宠物才能开始聚会")
    pets: list[Pet] = []
    for member in accepted:
        pet = _require_managed_pet(session, member.account_id, str(member.pet_id))
        _ensure_pet_available(session, pet, exclude_party_id=party.id)
        pets.append(pet)
    now = datetime.now(UTC)
    party.status = "active"
    party.started_at = now
    party.scheduled_end_at = now + timedelta(minutes=party.duration_minutes)
    for member in values:
        if member.status == "accepted":
            member.status = "joined"
            member.joined_at = now
        elif member.status == "invited":
            member.status = "expired"
            member.responded_at = now
    for pet in pets:
        pet.presence = "gathering"
        pet.state_version += 1
        pet.updated_at = now
        session.flush()
        publish_party_pet(session, party, pet, cause="party_started")
    session.flush()
    publish_party_update(session, party, cause="party_started", members=values)
    result = _view(session, party, principal)
    session.commit()
    return result


@party_router.post("/{party_id}/leave", response_model=PartyView)
def leave_party(
    party_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyView:
    settle_due_parties(session)
    party = _party(session, party_id)
    member = _require_membership(session, party, principal.account_id)
    if party.status != "active" or member.status != "joined":
        raise HTTPException(status_code=409, detail="当前不能离开该聚会")
    if member.role == "host":
        raise HTTPException(status_code=409, detail="发起人需要使用结束聚会操作")
    now = datetime.now(UTC)
    member.status = "left"
    member.left_at = now
    if member.pet_id:
        pet = session.get(Pet, member.pet_id)
        if pet is not None:
            if pet.presence == "gathering":
                pet.presence = "home"
            pet.state_version += 1
            pet.updated_at = now
            session.flush()
            publish_party_pet(session, party, pet, cause="party_member_left")
    session.flush()
    remaining = [item for item in party_members(session, party.id) if item.status == "joined"]
    if len(remaining) <= 1:
        finish_party(
            session,
            party,
            now=now,
            reason="party_no_longer_has_guests",
        )
    else:
        publish_party_update(session, party, cause=f"party_member_left:{member.id}")
    result = _view(session, party, principal)
    session.commit()
    return result


@party_router.post("/{party_id}/cancel", response_model=PartyView)
def cancel_party(
    party_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyView:
    settle_due_parties(session)
    party = _party(session, party_id)
    if party.host_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有聚会发起人可以取消聚会")
    if party.status != "open":
        raise HTTPException(status_code=409, detail="只有尚未开始的聚会可以取消")
    finish_party(
        session,
        party,
        now=datetime.now(UTC),
        reason="party_cancelled",
        cancelled=True,
    )
    result = _view(session, party, principal)
    session.commit()
    return result


@party_router.post("/{party_id}/end", response_model=PartyView)
def end_party(
    party_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyView:
    settle_due_parties(session)
    party = _party(session, party_id)
    if party.host_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有聚会发起人可以结束聚会")
    if party.status != "active":
        raise HTTPException(status_code=409, detail="只有进行中的聚会可以结束")
    finish_party(
        session,
        party,
        now=datetime.now(UTC),
        reason="party_host_ended",
    )
    result = _view(session, party, principal)
    session.commit()
    return result


@party_router.post(
    "/{party_id}/interactions/{action}",
    response_model=PartyInteractionView,
)
def interact_during_party(
    party_id: str,
    action: PartyInteractionAction,
    body: PartyInteractionRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PartyInteractionView:
    settle_due_parties(session)
    party = _party(session, party_id)
    member = _require_membership(session, party, principal.account_id)
    if party.status != "active" or member.status != "joined":
        raise HTTPException(status_code=409, detail="只有正在参加聚会的成员可以互动")
    scoped_key = f"party-interaction:{party.id}:{body.idempotency_key}"
    existing = find_event_by_idempotency(session, principal.account_id, scoped_key)
    if existing is not None:
        if existing.event_type != "pet_party_interaction":
            raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
        interaction = _payload(existing).get("interaction")
        if not isinstance(interaction, dict):
            raise HTTPException(status_code=409, detail="幂等记录缺少互动结果")
        return PartyInteractionView.model_validate(interaction)
    joined = [item for item in party_members(session, party.id) if item.status == "joined"]
    pet_ids = [str(item.pet_id) for item in joined if item.pet_id]
    now = datetime.now(UTC)
    result = PartyInteractionView(
        interaction_id=str(uuid4()),
        party_id=party.id,
        action=action,
        actor_account_id=principal.account_id,
        pet_ids=pet_ids,
        created_at=now,
    )
    payload = {
        "cause": "pet_party_interaction",
        "interaction": result.model_dump(mode="json"),
    }
    for account_id in {item.account_id for item in joined}:
        append_event(
            session,
            account_id=account_id,
            event_type="pet_party_interaction",
            idempotency_key=scoped_key,
            payload=payload,
        )
    session.commit()
    return result
