"""Customer-facing message search, unread navigation, and synchronized quick replies.

The module is intentionally projection-only. Search and unread navigation read the existing
conversation/message tables, while quick-reply preferences are stored as account-scoped sync
events so Web and bound desktop devices share one configuration without a new settings table.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .message_center_api import project_account_messages
from .messaging_api import (
    SYSTEM_UNREAD_MESSAGE_TYPES,
    ConversationView,
    MessageView,
    _conversation_view,
    _member,
    _member_accounts,
    _message_view,
)
from .models import Conversation, ConversationMember, Message, Pet, SyncEvent
from .security import Principal
from .services import append_event


message_efficiency_router = APIRouter(prefix="/api/v1", tags=["messaging"])

QuickReplyCategory = Literal["direct", "friend_pet", "visit", "shared_care"]
SearchMatchField = Literal["contact", "pet", "content", "title"]
QUICK_REPLY_EVENT = "message_quick_replies_updated"

DEFAULT_QUICK_REPLIES: dict[str, list[str]] = {
    "direct": ["收到", "好的，谢谢", "我稍后回复你"],
    "friend_pet": ["好可爱", "收到啦", "下次一起玩"],
    "visit": ["收到，我来看看", "可以，稍后处理", "谢谢，宠物已经到家"],
    "shared_care": ["收到，我会留意", "好的，谢谢", "我稍后处理"],
}


class MessageSearchResultView(BaseModel):
    conversation: ConversationView
    matched_message: MessageView | None = None
    matched_pet_id: str | None = None
    matched_pet_name: str | None = None
    matched_fields: list[SearchMatchField]
    snippet: str


class MessageSearchResponse(BaseModel):
    query: str
    count: int
    items: list[MessageSearchResultView]


class MessageWindowView(BaseModel):
    conversation_id: str
    center_sequence: int
    items: list[MessageView]
    has_earlier: bool
    has_later: bool


class UnreadNavigationView(BaseModel):
    conversation_id: str
    unread_count: int
    last_read_sequence: int
    first: MessageView | None
    previous: MessageView | None
    current: MessageView | None
    next: MessageView | None


class QuickReplyPreferenceView(BaseModel):
    categories: dict[str, list[str]]
    defaults: dict[str, list[str]]
    updated_at: datetime | None = None


class QuickReplyPreferenceUpdate(BaseModel):
    categories: dict[str, list[str]]

    @field_validator("categories")
    @classmethod
    def _validate_categories(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        return _normalize_partial_categories(value)


class QuickReplyResetRequest(BaseModel):
    category: Literal["all", "direct", "friend_pet", "visit", "shared_care"] = "all"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _payload(event: SyncEvent) -> dict[str, object]:
    try:
        value = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _normalize_replies(values: object) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("快捷回复必须使用列表")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        if len(text) > 80:
            raise ValueError("单条快捷回复不能超过 80 个字符")
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    if not 1 <= len(normalized) <= 6:
        raise ValueError("每类快捷回复需要保留 1 至 6 条")
    return normalized


def _normalize_partial_categories(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict) or not value:
        raise ValueError("至少需要修改一类快捷回复")
    normalized: dict[str, list[str]] = {}
    for raw_category, replies in value.items():
        category = str(raw_category).strip()
        if category not in DEFAULT_QUICK_REPLIES:
            raise ValueError(f"不支持的快捷回复分类：{category}")
        normalized[category] = _normalize_replies(replies)
    return normalized


def _quick_reply_preferences(
    session: Session,
    account_id: str,
) -> tuple[dict[str, list[str]], datetime | None]:
    row = session.scalar(
        select(SyncEvent)
        .where(
            SyncEvent.account_id == account_id,
            SyncEvent.event_type == QUICK_REPLY_EVENT,
        )
        .order_by(SyncEvent.sequence.desc())
        .limit(1)
    )
    categories = {key: list(values) for key, values in DEFAULT_QUICK_REPLIES.items()}
    if row is None:
        return categories, None
    raw = _payload(row).get("categories")
    if isinstance(raw, dict):
        for category, values in raw.items():
            if category not in categories:
                continue
            try:
                categories[category] = _normalize_replies(values)
            except ValueError:
                continue
    return categories, _aware(row.created_at)


def _quick_reply_view(
    categories: dict[str, list[str]],
    updated_at: datetime | None,
) -> QuickReplyPreferenceView:
    return QuickReplyPreferenceView(
        categories={key: list(values) for key, values in categories.items()},
        defaults={key: list(values) for key, values in DEFAULT_QUICK_REPLIES.items()},
        updated_at=updated_at,
    )


def _write_quick_replies(
    session: Session,
    *,
    principal: Principal,
    categories: dict[str, list[str]],
    cause: str,
) -> QuickReplyPreferenceView:
    now = datetime.now(UTC)
    append_event(
        session,
        account_id=principal.account_id,
        event_type=QUICK_REPLY_EVENT,
        idempotency_key=f"message-quick-replies:{principal.account_id}:{uuid4()}",
        payload={
            "cause": cause,
            "updated_by": principal.kind,
            "categories": categories,
        },
    )
    session.commit()
    return _quick_reply_view(categories, now)


def _snippet(content: str, query: str, limit: int = 180) -> str:
    text = " ".join(content.split())
    if len(text) <= limit:
        return text
    folded = text.casefold()
    index = folded.find(query.casefold())
    if index < 0:
        return text[: limit - 1] + "…"
    start = max(0, index - limit // 3)
    end = min(len(text), start + limit)
    if end - start < limit:
        start = max(0, end - limit)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def _accessible_conversations(
    session: Session,
    account_id: str,
    *,
    limit: int = 200,
) -> list[Conversation]:
    return list(
        session.scalars(
            select(Conversation)
            .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
            .where(ConversationMember.account_id == account_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .limit(limit)
        )
    )


def _message_matches(
    *,
    message: Message,
    query: str,
    sender_name: str,
    pet_name: str,
) -> list[SearchMatchField]:
    fields: list[SearchMatchField] = []
    folded = query.casefold()
    if folded in message.content.casefold() or folded in sender_name.casefold():
        fields.append("content")
    if pet_name and folded in pet_name.casefold():
        fields.append("pet")
    return fields


def _unread_condition(account_id: str):
    return or_(
        Message.sender_account_id != account_id,
        Message.message_type.in_(SYSTEM_UNREAD_MESSAGE_TYPES),
    )


def _unread_message(
    session: Session,
    *,
    conversation_id: str,
    account_id: str,
    last_read_sequence: int,
    direction: Literal["first", "previous", "current", "next"],
    current_sequence: int | None,
) -> Message | None:
    statement = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.sequence > last_read_sequence,
        _unread_condition(account_id),
    )
    if direction == "first":
        statement = statement.order_by(Message.sequence).limit(1)
    elif direction == "previous":
        if current_sequence is None:
            return None
        statement = (
            statement.where(Message.sequence < current_sequence)
            .order_by(Message.sequence.desc())
            .limit(1)
        )
    elif direction == "current":
        if current_sequence is None:
            return None
        statement = statement.where(Message.sequence == current_sequence).limit(1)
    else:
        if current_sequence is None:
            return None
        statement = (
            statement.where(Message.sequence > current_sequence)
            .order_by(Message.sequence)
            .limit(1)
        )
    return session.scalar(statement)


@message_efficiency_router.get("/message-search", response_model=MessageSearchResponse)
def search_messages(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    query: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
) -> MessageSearchResponse:
    normalized = " ".join(query.split())
    if not normalized:
        raise HTTPException(status_code=422, detail="搜索内容不能为空")
    project_account_messages(session, principal.account_id)
    session.flush()
    conversations = _accessible_conversations(session, principal.account_id)
    ids = [item.id for item in conversations]
    messages = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id.in_(ids))
            .order_by(Message.created_at.desc(), Message.sequence.desc())
            .limit(20000)
        )
    ) if ids else []
    grouped: dict[str, list[Message]] = defaultdict(list)
    account_ids = {message.sender_account_id for message in messages}
    pet_ids = {message.sender_pet_id for message in messages if message.sender_pet_id}
    accounts = {
        account.id: account
        for account in session.scalars(select(__import__("mypets_backend.models", fromlist=["Account"]).Account).where(__import__("mypets_backend.models", fromlist=["Account"]).Account.id.in_(account_ids)))
    } if account_ids else {}
    pets = {
        pet.id: pet
        for pet in session.scalars(select(Pet).where(Pet.id.in_(pet_ids)))
    } if pet_ids else {}
    for message in messages:
        grouped[message.conversation_id].append(message)

    results: list[tuple[datetime, MessageSearchResultView]] = []
    folded = normalized.casefold()
    for conversation in conversations:
        fields: list[SearchMatchField] = []
        snippets: list[str] = []
        matched_message: Message | None = None
        matched_pet: Pet | None = None
        accounts_in_conversation = _member_accounts(session, conversation.id)
        peers = [account for account in accounts_in_conversation if account.id != principal.account_id]
        contact_text = " ".join(
            value
            for peer in peers
            for value in (peer.display_name, peer.username)
            if value
        )
        if folded in conversation.title.casefold():
            fields.append("title")
            snippets.append(conversation.title)
        if contact_text and folded in contact_text.casefold():
            fields.append("contact")
            snippets.append(contact_text)
        for message in grouped.get(conversation.id, []):
            sender = accounts.get(message.sender_account_id)
            pet = pets.get(message.sender_pet_id) if message.sender_pet_id else None
            message_fields = _message_matches(
                message=message,
                query=normalized,
                sender_name=sender.display_name if sender is not None else "",
                pet_name=pet.name if pet is not None else "",
            )
            if not message_fields:
                continue
            matched_message = message
            matched_pet = pet
            for field in message_fields:
                if field not in fields:
                    fields.append(field)
            snippets.append(_snippet(message.content, normalized))
            break
        if not fields:
            continue
        timestamp = _aware(matched_message.created_at if matched_message else conversation.updated_at)
        assert timestamp is not None
        results.append(
            (
                timestamp,
                MessageSearchResultView(
                    conversation=_conversation_view(session, conversation, principal.account_id),
                    matched_message=_message_view(session, matched_message) if matched_message else None,
                    matched_pet_id=matched_pet.id if matched_pet else None,
                    matched_pet_name=matched_pet.name if matched_pet else None,
                    matched_fields=fields,
                    snippet=next((text for text in reversed(snippets) if text), "匹配到相关会话"),
                ),
            )
        )
    results.sort(key=lambda item: (item[0], item[1].conversation.conversation_id), reverse=True)
    session.commit()
    items = [item for _timestamp, item in results[:limit]]
    return MessageSearchResponse(query=normalized, count=len(results), items=items)


@message_efficiency_router.get(
    "/conversations/{conversation_id}/message-window",
    response_model=MessageWindowView,
)
def get_message_window(
    conversation_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    center_sequence: int | None = Query(default=None, ge=1),
    before: int = Query(default=40, ge=0, le=100),
    after: int = Query(default=40, ge=0, le=100),
) -> MessageWindowView:
    _member(session, conversation_id, principal.account_id)
    if center_sequence is None:
        center_sequence = int(
            session.scalar(
                select(func.max(Message.sequence)).where(Message.conversation_id == conversation_id)
            )
            or 0
        )
    if center_sequence <= 0:
        return MessageWindowView(
            conversation_id=conversation_id,
            center_sequence=0,
            items=[],
            has_earlier=False,
            has_later=False,
        )
    earlier_rows = list(
        session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.sequence <= center_sequence,
            )
            .order_by(Message.sequence.desc())
            .limit(before + 1)
        )
    )
    later_rows = list(
        session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.sequence > center_sequence,
            )
            .order_by(Message.sequence)
            .limit(after + 1)
        )
    )
    has_earlier = len(earlier_rows) > before
    has_later = len(later_rows) > after
    rows = list(reversed(earlier_rows[: before + 1])) + later_rows[:after]
    unique: dict[str, Message] = {row.id: row for row in rows}
    ordered = sorted(unique.values(), key=lambda item: item.sequence)
    return MessageWindowView(
        conversation_id=conversation_id,
        center_sequence=center_sequence,
        items=[_message_view(session, item) for item in ordered],
        has_earlier=has_earlier,
        has_later=has_later,
    )


@message_efficiency_router.get(
    "/conversations/{conversation_id}/unread-navigation",
    response_model=UnreadNavigationView,
)
def get_unread_navigation(
    conversation_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    current_sequence: int | None = Query(default=None, ge=1),
) -> UnreadNavigationView:
    member = _member(session, conversation_id, principal.account_id)
    last_read = int(member.last_read_sequence or 0)
    unread_count = int(
        session.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id == conversation_id,
                Message.sequence > last_read,
                _unread_condition(principal.account_id),
            )
        )
        or 0
    )
    first = _unread_message(
        session,
        conversation_id=conversation_id,
        account_id=principal.account_id,
        last_read_sequence=last_read,
        direction="first",
        current_sequence=None,
    )
    current = _unread_message(
        session,
        conversation_id=conversation_id,
        account_id=principal.account_id,
        last_read_sequence=last_read,
        direction="current",
        current_sequence=current_sequence,
    )
    if current is None and current_sequence is None:
        current = first
    anchor = current.sequence if current is not None else current_sequence
    previous = _unread_message(
        session,
        conversation_id=conversation_id,
        account_id=principal.account_id,
        last_read_sequence=last_read,
        direction="previous",
        current_sequence=anchor,
    )
    next_message = _unread_message(
        session,
        conversation_id=conversation_id,
        account_id=principal.account_id,
        last_read_sequence=last_read,
        direction="next",
        current_sequence=anchor,
    )
    return UnreadNavigationView(
        conversation_id=conversation_id,
        unread_count=unread_count,
        last_read_sequence=last_read,
        first=_message_view(session, first) if first else None,
        previous=_message_view(session, previous) if previous else None,
        current=_message_view(session, current) if current else None,
        next=_message_view(session, next_message) if next_message else None,
    )


@message_efficiency_router.get(
    "/message-quick-replies",
    response_model=QuickReplyPreferenceView,
)
def get_message_quick_replies(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> QuickReplyPreferenceView:
    categories, updated_at = _quick_reply_preferences(session, principal.account_id)
    return _quick_reply_view(categories, updated_at)


@message_efficiency_router.patch(
    "/message-quick-replies",
    response_model=QuickReplyPreferenceView,
)
def update_message_quick_replies(
    body: QuickReplyPreferenceUpdate,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> QuickReplyPreferenceView:
    current, _updated_at = _quick_reply_preferences(session, principal.account_id)
    current.update(body.categories)
    return _write_quick_replies(
        session,
        principal=principal,
        categories=current,
        cause="customer_updated",
    )


@message_efficiency_router.post(
    "/message-quick-replies/reset",
    response_model=QuickReplyPreferenceView,
)
def reset_message_quick_replies(
    body: QuickReplyResetRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> QuickReplyPreferenceView:
    current, _updated_at = _quick_reply_preferences(session, principal.account_id)
    if body.category == "all":
        current = {key: list(values) for key, values in DEFAULT_QUICK_REPLIES.items()}
    else:
        current[body.category] = list(DEFAULT_QUICK_REPLIES[body.category])
    return _write_quick_replies(
        session,
        principal=principal,
        categories=current,
        cause="customer_reset_default",
    )
