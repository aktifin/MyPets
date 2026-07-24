"""Parse server synchronization contracts and apply them to the local SQLite cache.

The module has no networking dependency. HTTP transport can be added independently; every
payload is fully validated before the local cache is mutated. Unknown future event types are
ignored but their cursor is advanced so older clients do not become permanently stuck.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .domain import (
    AccountPetRelation,
    CloudEvent,
    GrowthStage,
    PetIdentity,
    PetProfile,
    PetRole,
    PetStats,
    PresenceStatus,
)
from .local_store import LocalStateStore

SYNC_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class SyncApplyResult:
    account_id: str
    device_id: str
    cursor: int
    pets_applied: int = 0
    relations_applied: int = 0
    events_applied: int = 0
    events_ignored: int = 0


def stream_name(account_id: str, device_id: str) -> str:
    account_id = account_id.strip()
    device_id = device_id.strip()
    if not account_id or not device_id:
        raise ValueError("账户和设备标识不能为空")
    return f"sync:{account_id}:{device_id}"


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是 JSON 对象")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} 必须是 JSON 数组")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def _integer(
    value: Any,
    field: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} 必须是整数")
    if value < minimum:
        raise ValueError(f"{field} 不能小于 {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field} 不能大于 {maximum}")
    return value


def _timestamp(value: Any, field: str) -> datetime:
    raw = _string(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 不是有效 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须包含时区")
    return parsed


def parse_pet(value: Any) -> PetProfile:
    data = _mapping(value, "pet")
    stats_data = _mapping(data.get("stats"), "pet.stats")
    try:
        stage = GrowthStage(_string(stats_data.get("growth_stage"), "growth_stage"))
        presence = PresenceStatus(_string(data.get("presence"), "presence"))
    except ValueError as exc:
        raise ValueError(f"宠物枚举值无效：{exc}") from exc
    profile = PetProfile(
        identity=PetIdentity(
            pet_id=_string(data.get("pet_id"), "pet_id"),
            name=_string(data.get("name"), "name"),
            template_id=_string(data.get("template_id"), "template_id"),
            template_version=_string(
                data.get("template_version"), "template_version"
            ),
            identity_version=_string(
                data.get("identity_version"), "identity_version"
            ),
            primary_owner_account_id=_string(
                data.get("primary_owner_account_id"),
                "primary_owner_account_id",
            ),
        ),
        stats=PetStats(
            growth_stage=stage,
            growth_level=_integer(
                stats_data.get("growth_level"), "growth_level", minimum=1
            ),
            growth_exp=_integer(stats_data.get("growth_exp"), "growth_exp"),
            bond_level=_integer(
                stats_data.get("bond_level"), "bond_level", minimum=1
            ),
            bond_exp=_integer(stats_data.get("bond_exp"), "bond_exp"),
            hunger=_integer(stats_data.get("hunger"), "hunger", maximum=100),
            energy=_integer(stats_data.get("energy"), "energy", maximum=100),
            mood=_integer(stats_data.get("mood"), "mood", maximum=100),
            cleanliness=_integer(
                stats_data.get("cleanliness"), "cleanliness", maximum=100
            ),
            health=_integer(stats_data.get("health"), "health", maximum=100),
            boredom=_integer(
                stats_data.get("boredom"), "boredom", maximum=100
            ),
            state_version=_integer(
                stats_data.get("state_version"), "state_version", minimum=1
            ),
        ),
        presence=presence,
        personality_type=_string(data.get("personality_type"), "personality_type"),
        asset_version=_string(data.get("asset_version"), "asset_version"),
        updated_at=_timestamp(data.get("updated_at"), "updated_at"),
    )
    profile.normalize()
    return profile


def parse_relation(value: Any) -> AccountPetRelation:
    data = _mapping(value, "relation")
    try:
        role = PetRole(_string(data.get("role"), "role"))
    except ValueError as exc:
        raise ValueError(f"宠物关系角色无效：{exc}") from exc
    return AccountPetRelation(
        account_id=_string(data.get("account_id"), "account_id"),
        pet_id=_string(data.get("pet_id"), "pet_id"),
        role=role,
        affinity=_integer(data.get("affinity"), "affinity", maximum=100),
        care_contribution=_integer(
            data.get("care_contribution"), "care_contribution"
        ),
    )


def parse_event(value: Any) -> CloudEvent:
    data = _mapping(value, "event")
    target_device_id = data.get("target_device_id")
    if target_device_id is not None:
        target_device_id = _string(target_device_id, "target_device_id")
    return CloudEvent(
        event_id=_string(data.get("event_id"), "event_id"),
        event_type=_string(data.get("event_type"), "event_type"),
        sequence_number=_integer(
            data.get("sequence_number"), "sequence_number", minimum=1
        ),
        idempotency_key=_string(data.get("idempotency_key"), "idempotency_key"),
        created_at=_timestamp(data.get("created_at"), "created_at"),
        payload=dict(_mapping(data.get("payload"), "payload")),
        target_account_id=_string(
            data.get("target_account_id"), "target_account_id"
        ),
        target_device_id=target_device_id,
    )


def apply_bootstrap(store: LocalStateStore, payload: Mapping[str, Any]) -> SyncApplyResult:
    data = _mapping(payload, "bootstrap")
    if data.get("schema_version") != SYNC_SCHEMA_VERSION:
        raise ValueError("不支持的同步快照版本")
    account = _mapping(data.get("account"), "account")
    device = _mapping(data.get("device"), "device")
    account_id = _string(account.get("id"), "account.id")
    device_id = _string(device.get("id"), "device.id")
    cursor = _integer(data.get("cursor"), "cursor")
    pets = [parse_pet(item) for item in _list(data.get("pets"), "pets")]
    relations = [
        parse_relation(item) for item in _list(data.get("relations"), "relations")
    ]
    pet_ids = {pet.identity.pet_id for pet in pets}
    if len(pet_ids) != len(pets):
        raise ValueError("同步快照包含重复宠物")
    for relation in relations:
        if relation.account_id != account_id:
            raise ValueError("同步关系不属于当前账户")
        if relation.pet_id not in pet_ids:
            raise ValueError("同步关系引用了快照之外的宠物")
    active_pet_id = device.get("active_pet_id")
    if active_pet_id is not None:
        active_pet_id = _string(active_pet_id, "device.active_pet_id")
        if active_pet_id not in pet_ids:
            raise ValueError("当前宠物不在同步快照中")

    for pet in pets:
        store.upsert_pet(pet)
    for relation in relations:
        store.upsert_relation(relation)
    store.set_active_pet_id(active_pet_id)
    store.set_cursor(stream_name(account_id, device_id), cursor)
    return SyncApplyResult(
        account_id=account_id,
        device_id=device_id,
        cursor=cursor,
        pets_applied=len(pets),
        relations_applied=len(relations),
    )


def apply_events(
    store: LocalStateStore,
    payload: Mapping[str, Any],
    *,
    account_id: str,
    device_id: str,
) -> SyncApplyResult:
    data = _mapping(payload, "events response")
    events = [parse_event(item) for item in _list(data.get("events"), "events")]
    next_cursor = _integer(data.get("next_cursor"), "next_cursor")
    stream = stream_name(account_id, device_id)
    current = store.get_cursor(stream)
    applied = ignored = 0
    previous = current
    for event in events:
        if event.target_account_id != account_id:
            raise ValueError("同步事件不属于当前账户")
        if event.target_device_id not in {None, device_id}:
            raise ValueError("同步事件被发送给了其他设备")
        if event.sequence_number <= previous:
            continue
        previous = event.sequence_number
        if _apply_event(store, event, device_id=device_id):
            applied += 1
        else:
            ignored += 1
        store.set_cursor(stream, event.sequence_number)
    if next_cursor < previous:
        raise ValueError("next_cursor 不能小于已处理事件序号")
    store.set_cursor(stream, next_cursor)
    return SyncApplyResult(
        account_id=account_id,
        device_id=device_id,
        cursor=max(previous, next_cursor, current),
        events_applied=applied,
        events_ignored=ignored,
    )


def _apply_event(store: LocalStateStore, event: CloudEvent, *, device_id: str) -> bool:
    if event.event_type in {"pet_created", "pet_updated"}:
        pet = parse_pet(event.payload.get("pet"))
        store.upsert_pet(pet)
        relation_data = event.payload.get("relation")
        if relation_data is not None:
            store.upsert_relation(parse_relation(relation_data))
        return True
    if event.event_type == "pet_deleted":
        store.delete_pet(_string(event.payload.get("pet_id"), "pet_id"))
        return True
    if event.event_type == "relation_updated":
        store.upsert_relation(parse_relation(event.payload.get("relation")))
        return True
    if event.event_type == "active_pet_changed":
        event_device_id = _string(event.payload.get("device_id"), "device_id")
        if event_device_id != device_id:
            raise ValueError("当前宠物事件与设备不匹配")
        pet_id = event.payload.get("pet_id")
        if pet_id is not None:
            pet_id = _string(pet_id, "pet_id")
        store.set_active_pet_id(pet_id)
        return True
    return False
