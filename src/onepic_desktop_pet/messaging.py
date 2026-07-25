"""Validated desktop messaging records shared by sync, SQLite, and Qt UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

MESSAGE_TYPES = {"text", "visit_message", "care_event", "growth_notice"}
CONVERSATION_KINDS = {"direct", "system"}
CONVERSATION_CATEGORIES = {
    "direct",
    "friend_pet",
    "visit",
    "shared_care",
    "growth",
}


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是 JSON 对象")
    return value


def _string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串")
    result = value.strip()
    if not result and not allow_empty:
        raise ValueError(f"{field} 不能为空")
    return result


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} 必须是不小于 {minimum} 的整数")
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


@dataclass(frozen=True)
class MessageRecord:
    account_id: str
    message_id: str
    sequence_number: int
    conversation_id: str
    sender_account_id: str
    sender_display_name: str
    sender_pet_id: str | None
    message_type: str
    content: str
    created_at: datetime

    @property
    def outgoing(self) -> bool:
        return self.sender_account_id == self.account_id and self.message_type == "text"


@dataclass(frozen=True)
class MessageReceiptRecord:
    account_id: str
    message_id: str
    state: str
    delivered_at: datetime
    read_at: datetime | None


@dataclass(frozen=True)
class ConversationRecord:
    account_id: str
    conversation_id: str
    kind: str
    category: str
    category_label: str
    title: str
    peer_account_id: str | None
    peer_username: str | None
    peer_display_name: str | None
    last_message: MessageRecord | None
    unread_count: int
    updated_at: datetime


def parse_message(value: Any, *, account_id: str) -> MessageRecord:
    data = _mapping(value, "message")
    sender_pet_id = data.get("sender_pet_id")
    if sender_pet_id is not None:
        sender_pet_id = _string(sender_pet_id, "message.sender_pet_id")
    message_type = _string(data.get("message_type"), "message.message_type")
    if message_type not in MESSAGE_TYPES:
        raise ValueError("当前客户端不支持该消息类型")
    return MessageRecord(
        account_id=_string(account_id, "account_id"),
        message_id=_string(data.get("message_id"), "message.message_id"),
        sequence_number=_integer(
            data.get("sequence_number"), "message.sequence_number", minimum=1
        ),
        conversation_id=_string(
            data.get("conversation_id"), "message.conversation_id"
        ),
        sender_account_id=_string(
            data.get("sender_account_id"), "message.sender_account_id"
        ),
        sender_display_name=_string(
            data.get("sender_display_name"), "message.sender_display_name"
        ),
        sender_pet_id=sender_pet_id,
        message_type=message_type,
        content=_string(data.get("content"), "message.content"),
        created_at=_timestamp(data.get("created_at"), "message.created_at"),
    )


def parse_receipt(value: Any) -> MessageReceiptRecord:
    data = _mapping(value, "receipt")
    state = _string(data.get("state"), "receipt.state")
    if state not in {"delivered", "read"}:
        raise ValueError("消息回执状态无效")
    read_at = data.get("read_at")
    return MessageReceiptRecord(
        account_id=_string(data.get("account_id"), "receipt.account_id"),
        message_id=_string(data.get("message_id"), "receipt.message_id"),
        state=state,
        delivered_at=_timestamp(data.get("delivered_at"), "receipt.delivered_at"),
        read_at=_timestamp(read_at, "receipt.read_at") if read_at is not None else None,
    )


def parse_conversation(value: Any, *, account_id: str) -> ConversationRecord:
    data = _mapping(value, "conversation")
    kind = _string(data.get("kind"), "conversation.kind")
    if kind not in CONVERSATION_KINDS:
        raise ValueError("当前客户端不支持该会话类型")
    category = _string(data.get("category", "direct"), "conversation.category")
    if category not in CONVERSATION_CATEGORIES:
        raise ValueError("会话分类无效")
    peer_data = data.get("peer")
    peer_account_id = peer_username = peer_display_name = None
    if peer_data is not None:
        peer = _mapping(peer_data, "conversation.peer")
        peer_account_id = _string(peer.get("id"), "conversation.peer.id")
        peer_username = _string(peer.get("username"), "conversation.peer.username")
        peer_display_name = _string(
            peer.get("display_name"), "conversation.peer.display_name"
        )
    last_message_data = data.get("last_message")
    last_message = (
        parse_message(last_message_data, account_id=account_id)
        if last_message_data is not None
        else None
    )
    return ConversationRecord(
        account_id=_string(account_id, "account_id"),
        conversation_id=_string(
            data.get("conversation_id"), "conversation.conversation_id"
        ),
        kind=kind,
        category=category,
        category_label=_string(
            data.get("category_label", category),
            "conversation.category_label",
        ),
        title=_string(data.get("title"), "conversation.title"),
        peer_account_id=peer_account_id,
        peer_username=peer_username,
        peer_display_name=peer_display_name,
        last_message=last_message,
        unread_count=_integer(data.get("unread_count"), "conversation.unread_count"),
        updated_at=_timestamp(data.get("updated_at"), "conversation.updated_at"),
    )
