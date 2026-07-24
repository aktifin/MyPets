"""Direct conversations, text messages, read receipts, and sync events."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import (
    Account,
    AccountPetRelation,
    Conversation,
    ConversationMember,
    Message,
    MessageReceipt,
    SyncEvent,
)
from .schemas import AccountView
from .security import Principal, normalize_username
from .services import account_view, append_event, find_event_by_idempotency

messaging_router = APIRouter(prefix="/api/v1", tags=["messaging"])


class ConversationCreateRequest(BaseModel):
    recipient_username: str = Field(min_length=3, max_length=64)

    @field_validator("recipient_username")
    @classmethod
    def _normalize_recipient(cls, value: str) -> str:
        normalized = normalize_username(value)
        if not normalized:
            raise ValueError("收件人用户名不能为空")
        return normalized


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    sender_pet_id: str | None = Field(default=None, max_length=36)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息内容不能为空")
        return value


class MessageView(BaseModel):
    message_id: str
    sequence_number: int
    conversation_id: str
    sender_account_id: str
    sender_display_name: str
    sender_pet_id: str | None
    message_type: Literal["text"] = "text"
    content: str
    created_at: datetime


class MessageReceiptView(BaseModel):
    message_id: str
    account_id: str
    state: Literal["delivered", "read"]
    delivered_at: datetime
    read_at: datetime | None


class ConversationView(BaseModel):
    conversation_id: str
    kind: Literal["direct"] = "direct"
    title: str
    members: list[AccountView]
    peer: AccountView | None
    last_message: MessageView | None
    unread_count: int
    updated_at: datetime


class MessagesResponse(BaseModel):
    items: list[MessageView]
    next_sequence: int
    has_more: bool


class MessageMutationResponse(BaseModel):
    conversation: ConversationView
    message: MessageView
    receipt: MessageReceiptView
    idempotency_key: str | None = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _event_payload(event: SyncEvent) -> dict[str, Any]:
    try:
        value = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _member(
    session: Session,
    conversation_id: str,
    account_id: str,
) -> ConversationMember:
    member = session.get(ConversationMember, (conversation_id, account_id))
    if member is None:
        raise HTTPException(status_code=404, detail="会话不存在或无访问权限")
    return member


def _member_accounts(session: Session, conversation_id: str) -> list[Account]:
    return list(
        session.scalars(
            select(Account)
            .join(ConversationMember, ConversationMember.account_id == Account.id)
            .where(ConversationMember.conversation_id == conversation_id)
            .order_by(Account.id)
        )
    )


def _message_view(session: Session, message: Message) -> MessageView:
    sender = session.get(Account, message.sender_account_id)
    if sender is None:
        raise RuntimeError("消息发送账户不存在")
    return MessageView(
        message_id=message.id,
        sequence_number=message.sequence,
        conversation_id=message.conversation_id,
        sender_account_id=message.sender_account_id,
        sender_display_name=sender.display_name,
        sender_pet_id=message.sender_pet_id,
        message_type="text",
        content=message.content,
        created_at=_aware(message.created_at),
    )


def _receipt_view(receipt: MessageReceipt) -> MessageReceiptView:
    return MessageReceiptView(
        message_id=receipt.message_id,
        account_id=receipt.account_id,
        state="read" if receipt.state == "read" else "delivered",
        delivered_at=_aware(receipt.delivered_at),
        read_at=_aware(receipt.read_at) if receipt.read_at else None,
    )


def _last_message(session: Session, conversation_id: str) -> Message | None:
    return session.scalar(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.sequence.desc())
        .limit(1)
    )


def _conversation_view(
    session: Session,
    conversation: Conversation,
    account_id: str,
) -> ConversationView:
    member = _member(session, conversation.id, account_id)
    accounts = _member_accounts(session, conversation.id)
    peer = next((account for account in accounts if account.id != account_id), None)
    latest = _last_message(session, conversation.id)
    unread_count = int(
        session.scalar(
            select(func.count(Message.sequence)).where(
                Message.conversation_id == conversation.id,
                Message.sequence > int(member.last_read_sequence or 0),
                Message.sender_account_id != account_id,
            )
        )
        or 0
    )
    title = conversation.title.strip() or (peer.display_name if peer else "消息")
    return ConversationView(
        conversation_id=conversation.id,
        title=title,
        members=[account_view(account) for account in accounts],
        peer=account_view(peer) if peer else None,
        last_message=_message_view(session, latest) if latest else None,
        unread_count=unread_count,
        updated_at=_aware(conversation.updated_at),
    )


def _conversation_payload(
    session: Session,
    conversation: Conversation,
    account_id: str,
) -> dict[str, Any]:
    return _conversation_view(session, conversation, account_id).model_dump(mode="json")


@messaging_router.post(
    "/conversations",
    response_model=ConversationView,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    body: ConversationCreateRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ConversationView:
    prior = find_event_by_idempotency(session, principal.account_id, idempotency_key)
    if prior is not None:
        payload = _event_payload(prior)
        conversation_id = payload.get("conversation", {}).get("conversation_id")
        conversation = session.get(Conversation, conversation_id) if conversation_id else None
        if prior.event_type != "conversation_updated" or conversation is None:
            raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
        return _conversation_view(session, conversation, principal.account_id)

    recipient = session.scalar(
        select(Account).where(Account.username == body.recipient_username)
    )
    if recipient is None:
        raise HTTPException(status_code=404, detail="收件人账户不存在")
    if recipient.id == principal.account_id:
        raise HTTPException(status_code=409, detail="不能与自己创建私聊")

    direct_key = "|".join(sorted((principal.account_id, recipient.id)))
    conversation = session.scalar(
        select(Conversation).where(Conversation.direct_key == direct_key)
    )
    created = conversation is None
    if conversation is None:
        now = datetime.now(UTC)
        conversation = Conversation(
            id=str(uuid4()),
            kind="direct",
            direct_key=direct_key,
            created_by_account_id=principal.account_id,
            created_at=now,
            updated_at=now,
        )
        session.add(conversation)
        session.flush()
        session.add_all(
            [
                ConversationMember(
                    conversation_id=conversation.id,
                    account_id=principal.account_id,
                    last_read_sequence=0,
                    joined_at=now,
                ),
                ConversationMember(
                    conversation_id=conversation.id,
                    account_id=recipient.id,
                    last_read_sequence=0,
                    joined_at=now,
                ),
            ]
        )
        session.flush()
    else:
        _member(session, conversation.id, principal.account_id)

    member_ids = [principal.account_id, recipient.id]
    for account_id in member_ids:
        event_key = (
            idempotency_key
            if account_id == principal.account_id
            else f"{idempotency_key}:account:{account_id}"
        )
        append_event(
            session,
            account_id=account_id,
            event_type="conversation_updated",
            idempotency_key=event_key,
            payload={
                "cause": "conversation_created" if created else "conversation_opened",
                "conversation": _conversation_payload(session, conversation, account_id),
            },
        )
    session.commit()
    return _conversation_view(session, conversation, principal.account_id)


@messaging_router.get("/conversations", response_model=list[ConversationView])
def list_conversations(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ConversationView]:
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


@messaging_router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagesResponse,
)
def list_messages(
    conversation_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> MessagesResponse:
    _member(session, conversation_id, principal.account_id)
    rows = list(
        session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.sequence > after_sequence,
            )
            .order_by(Message.sequence)
            .limit(limit + 1)
        )
    )
    items = rows[:limit]
    next_sequence = items[-1].sequence if items else after_sequence
    return MessagesResponse(
        items=[_message_view(session, message) for message in items],
        next_sequence=next_sequence,
        has_more=len(rows) > limit,
    )


@messaging_router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    conversation_id: str,
    body: MessageCreateRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> MessageMutationResponse:
    member = _member(session, conversation_id, principal.account_id)
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    prior = find_event_by_idempotency(session, principal.account_id, idempotency_key)
    if prior is not None:
        payload = _event_payload(prior)
        message_id = payload.get("message", {}).get("message_id")
        message = session.scalar(select(Message).where(Message.id == message_id)) if message_id else None
        receipt = (
            session.get(MessageReceipt, (message.id, principal.account_id))
            if message is not None
            else None
        )
        if prior.event_type != "message_received" or message is None or receipt is None:
            raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
        return MessageMutationResponse(
            conversation=_conversation_view(session, conversation, principal.account_id),
            message=_message_view(session, message),
            receipt=_receipt_view(receipt),
            idempotency_key=idempotency_key,
        )

    if body.sender_pet_id is not None:
        relation = session.get(
            AccountPetRelation,
            (principal.account_id, body.sender_pet_id),
        )
        if relation is None:
            raise HTTPException(status_code=403, detail="不能使用无权访问的宠物身份发消息")

    now = datetime.now(UTC)
    message = Message(
        id=str(uuid4()),
        conversation_id=conversation.id,
        sender_account_id=principal.account_id,
        sender_pet_id=body.sender_pet_id,
        message_type="text",
        content=body.content,
        created_at=now,
    )
    session.add(message)
    session.flush()
    conversation.updated_at = now

    members = list(
        session.scalars(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation.id
            )
        )
    )
    receipts: dict[str, MessageReceipt] = {}
    for item in members:
        is_sender = item.account_id == principal.account_id
        if is_sender:
            item.last_read_sequence = max(int(item.last_read_sequence or 0), message.sequence)
        receipt = MessageReceipt(
            message_id=message.id,
            account_id=item.account_id,
            state="read" if is_sender else "delivered",
            delivered_at=now,
            read_at=now if is_sender else None,
        )
        session.add(receipt)
        receipts[item.account_id] = receipt
    session.flush()

    message_data = _message_view(session, message).model_dump(mode="json")
    for item in members:
        event_key = (
            idempotency_key
            if item.account_id == principal.account_id
            else f"{idempotency_key}:account:{item.account_id}"
        )
        append_event(
            session,
            account_id=item.account_id,
            event_type="message_received",
            idempotency_key=event_key,
            payload={
                "cause": "message_send",
                "conversation": _conversation_payload(session, conversation, item.account_id),
                "message": message_data,
                "receipt": _receipt_view(receipts[item.account_id]).model_dump(mode="json"),
            },
        )
    session.commit()
    return MessageMutationResponse(
        conversation=_conversation_view(session, conversation, principal.account_id),
        message=_message_view(session, message),
        receipt=_receipt_view(receipts[principal.account_id]),
        idempotency_key=idempotency_key,
    )


@messaging_router.post(
    "/messages/{message_id}/read",
    response_model=MessageMutationResponse,
)
def mark_message_read(
    message_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> MessageMutationResponse:
    message = session.scalar(select(Message).where(Message.id == message_id))
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    member = _member(session, message.conversation_id, principal.account_id)
    conversation = session.get(Conversation, message.conversation_id)
    assert conversation is not None

    now = datetime.now(UTC)
    member.last_read_sequence = max(int(member.last_read_sequence or 0), message.sequence)
    message_ids = list(
        session.scalars(
            select(Message.id).where(
                Message.conversation_id == message.conversation_id,
                Message.sequence <= message.sequence,
            )
        )
    )
    for current_message_id in message_ids:
        receipt = session.get(MessageReceipt, (current_message_id, principal.account_id))
        if receipt is None:
            receipt = MessageReceipt(
                message_id=current_message_id,
                account_id=principal.account_id,
                state="read",
                delivered_at=now,
                read_at=now,
            )
            session.add(receipt)
        else:
            receipt.state = "read"
            receipt.read_at = receipt.read_at or now
    session.flush()
    target_receipt = session.get(MessageReceipt, (message.id, principal.account_id))
    assert target_receipt is not None

    members = list(
        session.scalars(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation.id
            )
        )
    )
    for item in members:
        append_event(
            session,
            account_id=item.account_id,
            event_type="message_read",
            idempotency_key=(
                f"message-read:{principal.account_id}:{conversation.id}:"
                f"{message.sequence}:account:{item.account_id}"
            ),
            payload={
                "cause": "message_read",
                "conversation": _conversation_payload(session, conversation, item.account_id),
                "reader_account_id": principal.account_id,
                "through_sequence": message.sequence,
                "receipt": _receipt_view(target_receipt).model_dump(mode="json"),
            },
        )
    session.commit()
    return MessageMutationResponse(
        conversation=_conversation_view(session, conversation, principal.account_id),
        message=_message_view(session, message),
        receipt=_receipt_view(target_receipt),
    )
