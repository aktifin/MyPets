"""Friendship, privacy, blocking, and shared-care HTTP APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import Account, AccountPetRelation, Pet
from .schemas import PetView, RelationView
from .security import Principal, normalize_username
from .services import append_event, pet_view, relation_view
from .social_models import (
    AccountBlock,
    CaregiverInvitation,
    FriendRequest,
    Friendship,
    PetPrivacy,
)

social_router = APIRouter(prefix="/api/v1", tags=["social"])

FriendRequestStatus = Literal["pending", "accepted", "rejected", "cancelled"]
InvitationStatus = Literal["pending", "accepted", "rejected", "cancelled"]
PetVisibility = Literal["private", "caregivers", "friends", "public"]
SharedRole = Literal["caregiver", "viewer"]


class AccountSummary(BaseModel):
    account_id: str
    username: str
    display_name: str


class UsernameRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)

    @field_validator("username")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_username(value)


class FriendRequestView(BaseModel):
    request_id: str
    sender: AccountSummary
    recipient: AccountSummary
    status: FriendRequestStatus
    created_at: datetime
    responded_at: datetime | None


class FriendRequestsResponse(BaseModel):
    incoming: list[FriendRequestView]
    outgoing: list[FriendRequestView]


class FriendshipView(BaseModel):
    friendship_id: str
    friend: AccountSummary
    created_at: datetime


class BlockView(BaseModel):
    account: AccountSummary
    created_at: datetime


class PetPrivacyUpdate(BaseModel):
    visibility: PetVisibility
    allow_remote_care: bool = False


class PetPrivacyView(BaseModel):
    pet_id: str
    visibility: PetVisibility
    allow_remote_care: bool
    updated_at: datetime | None


class PublicPetView(BaseModel):
    pet_id: str
    name: str
    template_id: str
    identity_version: str
    growth_stage: str
    growth_level: int
    bond_level: int
    mood: int
    presence: str
    asset_version: str
    visibility: PetVisibility
    relation_role: str | None = None


class CaregiverInviteCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    role: SharedRole = "caregiver"

    @field_validator("username")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_username(value)


class CaregiverInvitationView(BaseModel):
    invitation_id: str
    pet: PetView
    invited_account: AccountSummary
    invited_by: AccountSummary
    role: SharedRole
    status: InvitationStatus
    created_at: datetime
    responded_at: datetime | None


class CaregiverInvitationsResponse(BaseModel):
    incoming: list[CaregiverInvitationView]
    outgoing: list[CaregiverInvitationView]


class CaregiverView(BaseModel):
    account: AccountSummary
    relation: RelationView


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _account_summary(account: Account) -> AccountSummary:
    return AccountSummary(
        account_id=account.id,
        username=account.username,
        display_name=account.display_name,
    )


def _account_by_username(session: Session, username: str) -> Account:
    account = session.scalar(select(Account).where(Account.username == normalize_username(username)))
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    return account


def _pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def _friendship(session: Session, left: str, right: str) -> Friendship | None:
    low, high = _pair(left, right)
    return session.scalar(
        select(Friendship).where(
            Friendship.account_low_id == low,
            Friendship.account_high_id == high,
        )
    )


def _are_friends(session: Session, left: str, right: str) -> bool:
    return _friendship(session, left, right) is not None


def _blocked(session: Session, left: str, right: str) -> bool:
    return (
        session.get(AccountBlock, (left, right)) is not None
        or session.get(AccountBlock, (right, left)) is not None
    )


def _privacy(session: Session, pet: Pet) -> PetPrivacy:
    value = session.get(PetPrivacy, pet.id)
    if value is None:
        value = PetPrivacy(
            pet_id=pet.id,
            visibility="private",
            allow_remote_care=False,
            updated_by_account_id=pet.primary_owner_account_id,
        )
        session.add(value)
        session.flush()
    return value


def _relation(session: Session, account_id: str, pet_id: str) -> AccountPetRelation | None:
    return session.get(AccountPetRelation, (account_id, pet_id))


def _require_pet_manager(
    session: Session,
    account_id: str,
    pet_id: str,
) -> tuple[Pet, AccountPetRelation]:
    pet = session.get(Pet, pet_id)
    relation = _relation(session, account_id, pet_id)
    if pet is None or relation is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    if relation.role not in {"owner", "co_owner"}:
        raise HTTPException(status_code=403, detail="当前角色不能管理共同照料")
    return pet, relation


def _friend_request_view(session: Session, value: FriendRequest) -> FriendRequestView:
    sender = session.get(Account, value.sender_account_id)
    recipient = session.get(Account, value.recipient_account_id)
    if sender is None or recipient is None:
        raise RuntimeError("好友申请引用了不存在的账户")
    return FriendRequestView(
        request_id=value.id,
        sender=_account_summary(sender),
        recipient=_account_summary(recipient),
        status=value.status,
        created_at=_aware(value.created_at),
        responded_at=_aware(value.responded_at),
    )


def _invite_view(session: Session, value: CaregiverInvitation) -> CaregiverInvitationView:
    pet = session.get(Pet, value.pet_id)
    invited = session.get(Account, value.invited_account_id)
    inviter = session.get(Account, value.invited_by_account_id)
    if pet is None or invited is None or inviter is None:
        raise RuntimeError("共同照料邀请引用了不存在的数据")
    return CaregiverInvitationView(
        invitation_id=value.id,
        pet=pet_view(pet),
        invited_account=_account_summary(invited),
        invited_by=_account_summary(inviter),
        role=value.role,
        status=value.status,
        created_at=_aware(value.created_at),
        responded_at=_aware(value.responded_at),
    )


def _emit_social_event(
    session: Session,
    *,
    account_id: str,
    event_type: str,
    key: str,
    payload: dict[str, object],
) -> None:
    append_event(
        session,
        account_id=account_id,
        event_type=event_type,
        idempotency_key=key,
        payload=payload,
    )


@social_router.post("/friend-requests", response_model=FriendRequestView, status_code=201)
def create_friend_request(
    body: UsernameRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> FriendRequestView:
    target = _account_by_username(session, body.username)
    if target.id == principal.account_id:
        raise HTTPException(status_code=400, detail="不能添加自己为好友")
    if _blocked(session, principal.account_id, target.id):
        raise HTTPException(status_code=403, detail="当前账户关系不允许发送好友申请")
    if _are_friends(session, principal.account_id, target.id):
        raise HTTPException(status_code=409, detail="双方已经是好友")
    pending = session.scalar(
        select(FriendRequest).where(
            FriendRequest.status == "pending",
            or_(
                (
                    (FriendRequest.sender_account_id == principal.account_id)
                    & (FriendRequest.recipient_account_id == target.id)
                ),
                (
                    (FriendRequest.sender_account_id == target.id)
                    & (FriendRequest.recipient_account_id == principal.account_id)
                ),
            ),
        )
    )
    if pending is not None:
        raise HTTPException(status_code=409, detail="双方已有待处理好友申请")
    value = FriendRequest(
        id=str(uuid4()),
        sender_account_id=principal.account_id,
        recipient_account_id=target.id,
        status="pending",
    )
    session.add(value)
    session.flush()
    view = _friend_request_view(session, value)
    payload = {"friend_request": view.model_dump(mode="json")}
    _emit_social_event(
        session,
        account_id=target.id,
        event_type="friend_request_received",
        key=f"friend-request:{value.id}:received",
        payload=payload,
    )
    _emit_social_event(
        session,
        account_id=principal.account_id,
        event_type="friend_request_updated",
        key=f"friend-request:{value.id}:created",
        payload=payload,
    )
    session.commit()
    return view


@social_router.get("/friend-requests", response_model=FriendRequestsResponse)
def list_friend_requests(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    status: Literal["pending", "accepted", "rejected", "cancelled", "all"] = Query("pending"),
) -> FriendRequestsResponse:
    condition = [] if status == "all" else [FriendRequest.status == status]
    incoming = list(
        session.scalars(
            select(FriendRequest)
            .where(FriendRequest.recipient_account_id == principal.account_id, *condition)
            .order_by(FriendRequest.created_at.desc())
            .limit(200)
        )
    )
    outgoing = list(
        session.scalars(
            select(FriendRequest)
            .where(FriendRequest.sender_account_id == principal.account_id, *condition)
            .order_by(FriendRequest.created_at.desc())
            .limit(200)
        )
    )
    return FriendRequestsResponse(
        incoming=[_friend_request_view(session, item) for item in incoming],
        outgoing=[_friend_request_view(session, item) for item in outgoing],
    )


def _respond_friend_request(
    session: Session,
    principal: Principal,
    request_id: str,
    action: Literal["accepted", "rejected", "cancelled"],
) -> FriendRequestView:
    value = session.get(FriendRequest, request_id)
    if value is None:
        raise HTTPException(status_code=404, detail="好友申请不存在")
    if value.status != "pending":
        raise HTTPException(status_code=409, detail="好友申请已经处理")
    if action == "cancelled":
        if value.sender_account_id != principal.account_id:
            raise HTTPException(status_code=403, detail="只有发送方可以取消申请")
    elif value.recipient_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有接收方可以处理申请")
    if action == "accepted" and _blocked(
        session, value.sender_account_id, value.recipient_account_id
    ):
        raise HTTPException(status_code=403, detail="当前账户关系不允许建立好友关系")

    now = datetime.now(UTC)
    value.status = action
    value.responded_at = now
    if action == "accepted":
        low, high = _pair(value.sender_account_id, value.recipient_account_id)
        friendship = _friendship(session, low, high)
        if friendship is None:
            friendship = Friendship(
                id=str(uuid4()),
                account_low_id=low,
                account_high_id=high,
                created_at=now,
            )
            session.add(friendship)
        other_pending = list(
            session.scalars(
                select(FriendRequest).where(
                    FriendRequest.id != value.id,
                    FriendRequest.status == "pending",
                    or_(
                        (
                            (FriendRequest.sender_account_id == low)
                            & (FriendRequest.recipient_account_id == high)
                        ),
                        (
                            (FriendRequest.sender_account_id == high)
                            & (FriendRequest.recipient_account_id == low)
                        ),
                    ),
                )
            )
        )
        for pending in other_pending:
            pending.status = "cancelled"
            pending.responded_at = now
    session.flush()
    view = _friend_request_view(session, value)
    payload = {"friend_request": view.model_dump(mode="json")}
    for account_id in {value.sender_account_id, value.recipient_account_id}:
        _emit_social_event(
            session,
            account_id=account_id,
            event_type="friend_request_updated",
            key=f"friend-request:{value.id}:{action}:account:{account_id}",
            payload=payload,
        )
        if action == "accepted":
            _emit_social_event(
                session,
                account_id=account_id,
                event_type="friendship_updated",
                key=f"friendship:{value.id}:created:account:{account_id}",
                payload={"cause": "friend_request_accepted", "friend_request": payload["friend_request"]},
            )
    session.commit()
    return view


@social_router.post("/friend-requests/{request_id}/accept", response_model=FriendRequestView)
def accept_friend_request(
    request_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> FriendRequestView:
    return _respond_friend_request(session, principal, request_id, "accepted")


@social_router.post("/friend-requests/{request_id}/reject", response_model=FriendRequestView)
def reject_friend_request(
    request_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> FriendRequestView:
    return _respond_friend_request(session, principal, request_id, "rejected")


@social_router.post("/friend-requests/{request_id}/cancel", response_model=FriendRequestView)
def cancel_friend_request(
    request_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> FriendRequestView:
    return _respond_friend_request(session, principal, request_id, "cancelled")


@social_router.get("/friends", response_model=list[FriendshipView])
def list_friends(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> list[FriendshipView]:
    values = list(
        session.scalars(
            select(Friendship)
            .where(
                or_(
                    Friendship.account_low_id == principal.account_id,
                    Friendship.account_high_id == principal.account_id,
                )
            )
            .order_by(Friendship.created_at.desc())
        )
    )
    result: list[FriendshipView] = []
    for value in values:
        friend_id = (
            value.account_high_id
            if value.account_low_id == principal.account_id
            else value.account_low_id
        )
        friend = session.get(Account, friend_id)
        if friend is not None:
            result.append(
                FriendshipView(
                    friendship_id=value.id,
                    friend=_account_summary(friend),
                    created_at=_aware(value.created_at),
                )
            )
    return result


@social_router.delete("/friends/{friend_account_id}", status_code=204)
def remove_friend(
    friend_account_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    value = _friendship(session, principal.account_id, friend_account_id)
    if value is None:
        raise HTTPException(status_code=404, detail="好友关系不存在")
    session.delete(value)
    for account_id in {principal.account_id, friend_account_id}:
        _emit_social_event(
            session,
            account_id=account_id,
            event_type="friendship_updated",
            key=f"friendship:{value.id}:removed:account:{account_id}",
            payload={"cause": "friend_removed", "friend_account_id": (
                friend_account_id if account_id == principal.account_id else principal.account_id
            )},
        )
    session.commit()


def _revoke_shared_relations_between(
    session: Session,
    left: str,
    right: str,
) -> list[tuple[str, str]]:
    relations = list(
        session.scalars(
            select(AccountPetRelation)
            .join(Pet, Pet.id == AccountPetRelation.pet_id)
            .where(
                AccountPetRelation.role.in_({"caregiver", "viewer"}),
                or_(
                    (
                        (AccountPetRelation.account_id == left)
                        & (Pet.primary_owner_account_id == right)
                    ),
                    (
                        (AccountPetRelation.account_id == right)
                        & (Pet.primary_owner_account_id == left)
                    ),
                ),
            )
        )
    )
    removed = [(item.account_id, item.pet_id) for item in relations]
    for relation in relations:
        session.delete(relation)
    return removed


@social_router.post("/blocks", response_model=BlockView, status_code=201)
def block_account(
    body: UsernameRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> BlockView:
    target = _account_by_username(session, body.username)
    if target.id == principal.account_id:
        raise HTTPException(status_code=400, detail="不能屏蔽自己")
    existing = session.get(AccountBlock, (principal.account_id, target.id))
    if existing is not None:
        return BlockView(account=_account_summary(target), created_at=_aware(existing.created_at))
    now = datetime.now(UTC)
    value = AccountBlock(
        blocker_account_id=principal.account_id,
        blocked_account_id=target.id,
        created_at=now,
    )
    session.add(value)
    friendship = _friendship(session, principal.account_id, target.id)
    if friendship is not None:
        session.delete(friendship)
    pending_requests = list(
        session.scalars(
            select(FriendRequest).where(
                FriendRequest.status == "pending",
                or_(
                    (
                        (FriendRequest.sender_account_id == principal.account_id)
                        & (FriendRequest.recipient_account_id == target.id)
                    ),
                    (
                        (FriendRequest.sender_account_id == target.id)
                        & (FriendRequest.recipient_account_id == principal.account_id)
                    ),
                ),
            )
        )
    )
    for request in pending_requests:
        request.status = "cancelled"
        request.responded_at = now
    pending_invites = list(
        session.scalars(
            select(CaregiverInvitation).where(
                CaregiverInvitation.status == "pending",
                or_(
                    (
                        (CaregiverInvitation.invited_account_id == principal.account_id)
                        & (CaregiverInvitation.invited_by_account_id == target.id)
                    ),
                    (
                        (CaregiverInvitation.invited_account_id == target.id)
                        & (CaregiverInvitation.invited_by_account_id == principal.account_id)
                    ),
                ),
            )
        )
    )
    for invite in pending_invites:
        invite.status = "cancelled"
        invite.responded_at = now
    removed_relations = _revoke_shared_relations_between(
        session, principal.account_id, target.id
    )
    for account_id, pet_id in removed_relations:
        _emit_social_event(
            session,
            account_id=account_id,
            event_type="pet_deleted",
            key=f"block:{principal.account_id}:{target.id}:pet:{pet_id}:account:{account_id}",
            payload={"cause": "account_blocked", "pet_id": pet_id},
        )
    _emit_social_event(
        session,
        account_id=principal.account_id,
        event_type="account_block_updated",
        key=f"block:{principal.account_id}:{target.id}:created",
        payload={"blocked_account": _account_summary(target).model_dump(mode="json")},
    )
    session.commit()
    return BlockView(account=_account_summary(target), created_at=now)


@social_router.get("/blocks", response_model=list[BlockView])
def list_blocks(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> list[BlockView]:
    values = list(
        session.scalars(
            select(AccountBlock)
            .where(AccountBlock.blocker_account_id == principal.account_id)
            .order_by(AccountBlock.created_at.desc())
        )
    )
    result: list[BlockView] = []
    for value in values:
        account = session.get(Account, value.blocked_account_id)
        if account is not None:
            result.append(BlockView(account=_account_summary(account), created_at=_aware(value.created_at)))
    return result


@social_router.delete("/blocks/{blocked_account_id}", status_code=204)
def unblock_account(
    blocked_account_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    value = session.get(AccountBlock, (principal.account_id, blocked_account_id))
    if value is None:
        raise HTTPException(status_code=404, detail="屏蔽关系不存在")
    session.delete(value)
    _emit_social_event(
        session,
        account_id=principal.account_id,
        event_type="account_block_updated",
        key=f"block:{principal.account_id}:{blocked_account_id}:removed",
        payload={"cause": "account_unblocked", "blocked_account_id": blocked_account_id},
    )
    session.commit()


@social_router.get("/pets/{pet_id}/privacy", response_model=PetPrivacyView)
def get_pet_privacy(
    pet_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PetPrivacyView:
    pet, _ = _require_pet_manager(session, principal.account_id, pet_id)
    value = _privacy(session, pet)
    session.commit()
    return PetPrivacyView(
        pet_id=pet.id,
        visibility=value.visibility,
        allow_remote_care=value.allow_remote_care,
        updated_at=_aware(value.updated_at),
    )


@social_router.patch("/pets/{pet_id}/privacy", response_model=PetPrivacyView)
def update_pet_privacy(
    pet_id: str,
    body: PetPrivacyUpdate,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PetPrivacyView:
    pet, _ = _require_pet_manager(session, principal.account_id, pet_id)
    value = _privacy(session, pet)
    value.visibility = body.visibility
    value.allow_remote_care = body.allow_remote_care
    value.updated_by_account_id = principal.account_id
    value.updated_at = datetime.now(UTC)
    session.flush()
    view = PetPrivacyView(
        pet_id=pet.id,
        visibility=value.visibility,
        allow_remote_care=value.allow_remote_care,
        updated_at=_aware(value.updated_at),
    )
    relations = list(
        session.scalars(select(AccountPetRelation).where(AccountPetRelation.pet_id == pet.id))
    )
    for relation in relations:
        _emit_social_event(
            session,
            account_id=relation.account_id,
            event_type="pet_privacy_updated",
            key=f"pet-privacy:{pet.id}:{value.updated_at.isoformat()}:account:{relation.account_id}",
            payload={"privacy": view.model_dump(mode="json")},
        )
    session.commit()
    return view


@social_router.get("/friends/{friend_account_id}/pets", response_model=list[PublicPetView])
def list_friend_pets(
    friend_account_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> list[PublicPetView]:
    if _blocked(session, principal.account_id, friend_account_id):
        raise HTTPException(status_code=403, detail="当前账户关系不允许查看宠物")
    are_friends = _are_friends(session, principal.account_id, friend_account_id)
    pets = list(
        session.scalars(
            select(Pet)
            .where(Pet.primary_owner_account_id == friend_account_id)
            .order_by(Pet.created_at, Pet.id)
        )
    )
    result: list[PublicPetView] = []
    for pet in pets:
        privacy = _privacy(session, pet)
        relation = _relation(session, principal.account_id, pet.id)
        allowed = relation is not None or privacy.visibility == "public"
        if privacy.visibility == "friends" and are_friends:
            allowed = True
        if privacy.visibility == "caregivers" and relation is not None:
            allowed = True
        if not allowed:
            continue
        result.append(
            PublicPetView(
                pet_id=pet.id,
                name=pet.name,
                template_id=pet.template_id,
                identity_version=pet.identity_version,
                growth_stage=pet.growth_stage,
                growth_level=pet.growth_level,
                bond_level=pet.bond_level,
                mood=pet.mood,
                presence=pet.presence,
                asset_version=pet.asset_version,
                visibility=privacy.visibility,
                relation_role=relation.role if relation is not None else None,
            )
        )
    session.commit()
    return result


@social_router.post(
    "/pets/{pet_id}/caregiver-invitations",
    response_model=CaregiverInvitationView,
    status_code=201,
)
def create_caregiver_invitation(
    pet_id: str,
    body: CaregiverInviteCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> CaregiverInvitationView:
    pet, _ = _require_pet_manager(session, principal.account_id, pet_id)
    target = _account_by_username(session, body.username)
    if target.id == principal.account_id:
        raise HTTPException(status_code=400, detail="不能邀请自己")
    if _blocked(session, principal.account_id, target.id):
        raise HTTPException(status_code=403, detail="当前账户关系不允许发送邀请")
    if not _are_friends(session, principal.account_id, target.id):
        raise HTTPException(status_code=409, detail="只能邀请好友共同照料")
    existing_relation = _relation(session, target.id, pet.id)
    if existing_relation is not None:
        raise HTTPException(status_code=409, detail="该账户已经拥有宠物关系")
    pending = session.scalar(
        select(CaregiverInvitation).where(
            CaregiverInvitation.pet_id == pet.id,
            CaregiverInvitation.invited_account_id == target.id,
            CaregiverInvitation.status == "pending",
        )
    )
    if pending is not None:
        raise HTTPException(status_code=409, detail="该共同照料邀请已经存在")
    value = CaregiverInvitation(
        id=str(uuid4()),
        pet_id=pet.id,
        invited_account_id=target.id,
        invited_by_account_id=principal.account_id,
        role=body.role,
        status="pending",
    )
    session.add(value)
    session.flush()
    view = _invite_view(session, value)
    payload = {"caregiver_invitation": view.model_dump(mode="json")}
    _emit_social_event(
        session,
        account_id=target.id,
        event_type="caregiver_invitation_received",
        key=f"caregiver-invite:{value.id}:received",
        payload=payload,
    )
    _emit_social_event(
        session,
        account_id=principal.account_id,
        event_type="caregiver_invitation_updated",
        key=f"caregiver-invite:{value.id}:created",
        payload=payload,
    )
    session.commit()
    return view


@social_router.get(
    "/caregiver-invitations",
    response_model=CaregiverInvitationsResponse,
)
def list_caregiver_invitations(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    status: Literal["pending", "accepted", "rejected", "cancelled", "all"] = Query("pending"),
) -> CaregiverInvitationsResponse:
    condition = [] if status == "all" else [CaregiverInvitation.status == status]
    incoming = list(
        session.scalars(
            select(CaregiverInvitation)
            .where(CaregiverInvitation.invited_account_id == principal.account_id, *condition)
            .order_by(CaregiverInvitation.created_at.desc())
            .limit(200)
        )
    )
    outgoing = list(
        session.scalars(
            select(CaregiverInvitation)
            .where(CaregiverInvitation.invited_by_account_id == principal.account_id, *condition)
            .order_by(CaregiverInvitation.created_at.desc())
            .limit(200)
        )
    )
    return CaregiverInvitationsResponse(
        incoming=[_invite_view(session, item) for item in incoming],
        outgoing=[_invite_view(session, item) for item in outgoing],
    )


def _respond_caregiver_invitation(
    session: Session,
    principal: Principal,
    invitation_id: str,
    action: Literal["accepted", "rejected", "cancelled"],
) -> CaregiverInvitationView:
    value = session.get(CaregiverInvitation, invitation_id)
    if value is None:
        raise HTTPException(status_code=404, detail="共同照料邀请不存在")
    if value.status != "pending":
        raise HTTPException(status_code=409, detail="共同照料邀请已经处理")
    if action == "cancelled":
        if value.invited_by_account_id != principal.account_id:
            raise HTTPException(status_code=403, detail="只有邀请方可以取消")
    elif value.invited_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有被邀请方可以处理")
    if action == "accepted" and _blocked(
        session, value.invited_account_id, value.invited_by_account_id
    ):
        raise HTTPException(status_code=403, detail="当前账户关系不允许接受邀请")

    now = datetime.now(UTC)
    value.status = action
    value.responded_at = now
    pet = session.get(Pet, value.pet_id)
    if pet is None:
        raise HTTPException(status_code=404, detail="宠物不存在")
    relation: AccountPetRelation | None = None
    if action == "accepted":
        if not _are_friends(session, value.invited_account_id, value.invited_by_account_id):
            raise HTTPException(status_code=409, detail="好友关系已失效")
        relation = _relation(session, value.invited_account_id, value.pet_id)
        if relation is None:
            relation = AccountPetRelation(
                account_id=value.invited_account_id,
                pet_id=value.pet_id,
                role=value.role,
                affinity=0,
                care_contribution=0,
                created_at=now,
            )
            session.add(relation)
        elif relation.role in {"owner", "co_owner"}:
            raise HTTPException(status_code=409, detail="账户已经拥有更高权限")
        elif relation.role == "viewer" and value.role == "caregiver":
            relation.role = "caregiver"
        session.flush()
        _emit_social_event(
            session,
            account_id=value.invited_account_id,
            event_type="pet_updated",
            key=f"caregiver-invite:{value.id}:pet-access",
            payload={
                "cause": "caregiver_invitation_accepted",
                "pet": pet_view(pet).model_dump(mode="json"),
                "relation": relation_view(relation).model_dump(mode="json"),
            },
        )
    session.flush()
    view = _invite_view(session, value)
    payload = {"caregiver_invitation": view.model_dump(mode="json")}
    for account_id in {value.invited_account_id, value.invited_by_account_id}:
        _emit_social_event(
            session,
            account_id=account_id,
            event_type="caregiver_invitation_updated",
            key=f"caregiver-invite:{value.id}:{action}:account:{account_id}",
            payload=payload,
        )
    session.commit()
    return view


@social_router.post(
    "/caregiver-invitations/{invitation_id}/accept",
    response_model=CaregiverInvitationView,
)
def accept_caregiver_invitation(
    invitation_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> CaregiverInvitationView:
    return _respond_caregiver_invitation(session, principal, invitation_id, "accepted")


@social_router.post(
    "/caregiver-invitations/{invitation_id}/reject",
    response_model=CaregiverInvitationView,
)
def reject_caregiver_invitation(
    invitation_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> CaregiverInvitationView:
    return _respond_caregiver_invitation(session, principal, invitation_id, "rejected")


@social_router.post(
    "/caregiver-invitations/{invitation_id}/cancel",
    response_model=CaregiverInvitationView,
)
def cancel_caregiver_invitation(
    invitation_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> CaregiverInvitationView:
    return _respond_caregiver_invitation(session, principal, invitation_id, "cancelled")


@social_router.get("/pets/{pet_id}/caregivers", response_model=list[CaregiverView])
def list_pet_caregivers(
    pet_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> list[CaregiverView]:
    _require_pet_manager(session, principal.account_id, pet_id)
    relations = list(
        session.scalars(
            select(AccountPetRelation)
            .where(
                AccountPetRelation.pet_id == pet_id,
                AccountPetRelation.role.in_({"caregiver", "viewer"}),
            )
            .order_by(AccountPetRelation.created_at)
        )
    )
    result: list[CaregiverView] = []
    for relation in relations:
        account = session.get(Account, relation.account_id)
        if account is not None:
            result.append(
                CaregiverView(
                    account=_account_summary(account),
                    relation=relation_view(relation),
                )
            )
    return result


@social_router.delete("/pets/{pet_id}/caregivers/{account_id}", status_code=204)
def remove_pet_caregiver(
    pet_id: str,
    account_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    relation = _relation(session, account_id, pet_id)
    if relation is None or relation.role not in {"caregiver", "viewer"}:
        raise HTTPException(status_code=404, detail="共同照料关系不存在")
    if account_id != principal.account_id:
        _require_pet_manager(session, principal.account_id, pet_id)
    session.delete(relation)
    _emit_social_event(
        session,
        account_id=account_id,
        event_type="pet_deleted",
        key=f"shared-care:{pet_id}:account:{account_id}:removed:{uuid4()}",
        payload={"cause": "shared_care_removed", "pet_id": pet_id},
    )
    session.commit()
