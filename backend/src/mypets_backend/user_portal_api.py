"""Account, pet selection, and safe pet configuration APIs for the user Web portal."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session, require_account
from .models import Account, AccountPetRelation, Pet
from .schemas import AccountView, PetView, RelationView
from .security import Principal, hash_password, verify_password
from .services import (
    account_view,
    append_event,
    pet_for_account,
    pet_view,
    pets_for_account,
    relation_view,
    relations_for_account,
)
from .social_models import PetPrivacy
from .user_portal_models import AccountWebPreference

user_portal_api_router = APIRouter(prefix="/api/v1/portal", tags=["user-portal"])

_PERSONALITIES = {
    "balanced",
    "playful",
    "gentle",
    "energetic",
    "sleepy",
    "curious",
}


class AccountProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def _strip_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("显示名称不能为空")
        return value


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def _different_password(self) -> "PasswordChangeRequest":
        if self.current_password == self.new_password:
            raise ValueError("新密码不能与当前密码相同")
        return self


class PortalPreferenceUpdate(BaseModel):
    selected_pet_id: str | None = Field(default=None, max_length=36)


class PortalPetConfigRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    personality_type: str | None = Field(default=None, max_length=64)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("宠物名称不能为空")
        return value

    @field_validator("personality_type")
    @classmethod
    def _known_personality(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in _PERSONALITIES:
            raise ValueError("不支持的宠物性格")
        return value

    @model_validator(mode="after")
    def _not_empty(self) -> "PortalPetConfigRequest":
        if self.name is None and self.personality_type is None:
            raise ValueError("至少需要修改一个宠物配置字段")
        return self


class PortalPrivacyView(BaseModel):
    visibility: Literal["private", "caregivers", "friends", "public"]
    allow_remote_care: bool


class PortalPetView(BaseModel):
    pet: PetView
    relation: RelationView
    selected: bool
    can_configure: bool
    privacy: PortalPrivacyView


class PortalDashboard(BaseModel):
    account: AccountView
    selected_pet_id: str | None
    pets: list[PortalPetView]
    personalities: list[str]


class PortalPetConfigResponse(BaseModel):
    pet: PetView
    relation: RelationView


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


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


def _preference(session: Session, account_id: str) -> AccountWebPreference:
    value = session.get(AccountWebPreference, account_id)
    if value is None:
        value = AccountWebPreference(account_id=account_id, selected_pet_id=None)
        session.add(value)
        session.flush()
    return value


def _dashboard(session: Session, account: Account) -> PortalDashboard:
    pets = pets_for_account(session, account.id)
    relations = {
        relation.pet_id: relation for relation in relations_for_account(session, account.id)
    }
    preference = _preference(session, account.id)
    available_ids = {pet.id for pet in pets}
    if preference.selected_pet_id not in available_ids:
        preference.selected_pet_id = pets[0].id if pets else None
        preference.updated_at = datetime.now(UTC)
        session.flush()

    values: list[PortalPetView] = []
    for pet in pets:
        relation = relations[pet.id]
        privacy = _privacy(session, pet)
        values.append(
            PortalPetView(
                pet=pet_view(pet),
                relation=relation_view(relation),
                selected=pet.id == preference.selected_pet_id,
                can_configure=relation.role in {"owner", "co_owner"},
                privacy=PortalPrivacyView(
                    visibility=privacy.visibility,  # type: ignore[arg-type]
                    allow_remote_care=privacy.allow_remote_care,
                ),
            )
        )
    return PortalDashboard(
        account=account_view(account),
        selected_pet_id=preference.selected_pet_id,
        pets=values,
        personalities=sorted(_PERSONALITIES),
    )


@user_portal_api_router.get("/dashboard", response_model=PortalDashboard)
def portal_dashboard(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PortalDashboard:
    account = session.get(Account, principal.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    result = _dashboard(session, account)
    session.commit()
    return result


@user_portal_api_router.patch("/account", response_model=AccountView)
def update_account_profile(
    body: AccountProfileUpdate,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> AccountView:
    account = session.get(Account, principal.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    account.display_name = body.display_name
    account.updated_at = datetime.now(UTC)
    append_event(
        session,
        account_id=account.id,
        event_type="account_profile_updated",
        idempotency_key=f"portal-profile:{account.id}:{uuid4()}",
        payload={"account": account_view(account).model_dump(mode="json")},
    )
    session.commit()
    return account_view(account)


@user_portal_api_router.post("/account/password", status_code=204)
def change_account_password(
    body: PasswordChangeRequest,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    account = session.get(Account, principal.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    if not verify_password(body.current_password, account.password_hash):
        raise HTTPException(status_code=403, detail="当前密码不正确")
    account.password_hash = hash_password(body.new_password)
    account.updated_at = datetime.now(UTC)
    append_event(
        session,
        account_id=account.id,
        event_type="account_security_updated",
        idempotency_key=f"portal-password:{account.id}:{uuid4()}",
        payload={"cause": "password_changed"},
    )
    session.commit()


@user_portal_api_router.patch("/preference", response_model=PortalDashboard)
def update_portal_preference(
    body: PortalPreferenceUpdate,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> PortalDashboard:
    account = session.get(Account, principal.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    if body.selected_pet_id is not None and pet_for_account(
        session, account.id, body.selected_pet_id
    ) is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    preference = _preference(session, account.id)
    preference.selected_pet_id = body.selected_pet_id
    preference.updated_at = datetime.now(UTC)
    append_event(
        session,
        account_id=account.id,
        event_type="web_active_pet_changed",
        idempotency_key=f"portal-active-pet:{account.id}:{uuid4()}",
        payload={"pet_id": body.selected_pet_id},
    )
    result = _dashboard(session, account)
    session.commit()
    return result


@user_portal_api_router.patch(
    "/pets/{pet_id}", response_model=PortalPetConfigResponse
)
def update_portal_pet(
    pet_id: str,
    body: PortalPetConfigRequest,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> PortalPetConfigResponse:
    pet = session.get(Pet, pet_id)
    relation = session.get(AccountPetRelation, (principal.account_id, pet_id))
    if pet is None or relation is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    if relation.role not in {"owner", "co_owner"}:
        raise HTTPException(status_code=403, detail="当前角色不能修改宠物配置")

    changed = False
    if body.name is not None and body.name != pet.name:
        pet.name = body.name
        changed = True
    if body.personality_type is not None and body.personality_type != pet.personality_type:
        pet.personality_type = body.personality_type
        changed = True
    if changed:
        pet.state_version += 1
        pet.updated_at = datetime.now(UTC)
        session.flush()
        recipient_relations = list(
            session.scalars(
                select(AccountPetRelation).where(AccountPetRelation.pet_id == pet.id)
            )
        )
        for recipient_relation in recipient_relations:
            append_event(
                session,
                account_id=recipient_relation.account_id,
                event_type="pet_updated",
                idempotency_key=(
                    f"portal-pet-config:{pet.id}:{pet.state_version}:"
                    f"{recipient_relation.account_id}"
                ),
                payload={
                    "cause": "portal_pet_config",
                    "pet": pet_view(pet).model_dump(mode="json"),
                    "relation": relation_view(recipient_relation).model_dump(mode="json"),
                },
            )
    session.commit()
    return PortalPetConfigResponse(pet=pet_view(pet), relation=relation_view(relation))
