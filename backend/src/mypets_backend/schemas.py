"""Pydantic request and response contracts shared by the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=128)


class AccountView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    account: AccountView
    device_id: str | None = None


class DeviceBindRequest(BaseModel):
    public_id: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    platform: Literal["windows", "macos", "linux", "mini_program", "web"]


class DeviceTokenRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=36)
    device_secret: str = Field(min_length=32, max_length=256)


class DeviceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    public_id: str
    name: str
    platform: str
    active_pet_id: str | None
    last_seen_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class DeviceBindingResponse(BaseModel):
    device: DeviceView
    device_secret: str


class ActivePetRequest(BaseModel):
    pet_id: str | None = Field(default=None, max_length=36)


class PetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    template_id: str = Field(min_length=1, max_length=160)
    template_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    identity_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    asset_version: str = Field(default="1.0.0", min_length=1, max_length=32)

    @field_validator(
        "name",
        "template_id",
        "template_version",
        "identity_version",
        "asset_version",
    )
    @classmethod
    def _strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class PetStatsView(BaseModel):
    growth_stage: str
    growth_level: int
    growth_exp: int
    bond_level: int
    bond_exp: int
    hunger: int
    energy: int
    mood: int
    cleanliness: int
    health: int
    boredom: int
    state_version: int


class PetView(BaseModel):
    pet_id: str
    name: str
    template_id: str
    template_version: str
    identity_version: str
    primary_owner_account_id: str
    presence: str
    personality_type: str
    asset_version: str
    stats: PetStatsView
    updated_at: datetime


class RelationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    pet_id: str
    role: str
    affinity: int
    care_contribution: int


class BootstrapResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    server_time: datetime
    account: AccountView
    device: DeviceView
    pets: list[PetView]
    relations: list[RelationView]
    cursor: int


class SyncEventView(BaseModel):
    sequence_number: int
    event_id: str
    event_type: str
    idempotency_key: str
    created_at: datetime
    target_account_id: str
    target_device_id: str | None
    payload: dict[str, Any]


class EventsResponse(BaseModel):
    events: list[SyncEventView]
    next_cursor: int
    has_more: bool


class HeartbeatResponse(BaseModel):
    server_time: datetime
    cursor: int
