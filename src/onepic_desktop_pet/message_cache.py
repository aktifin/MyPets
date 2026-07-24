"""Account-scoped SQLite conversation, message, and receipt cache."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .local_store import LocalStateStore, _iso, _parse
from .messaging import ConversationRecord, MessageReceiptRecord, MessageRecord


class MessageCache:
    """Store rebuildable message snapshots in the existing local SQLite database."""

    def __init__(self, store: LocalStateStore) -> None:
        self.store = store
        self._connection = store._connection  # Shared transaction and WAL configuration.
        self.initialize()

    def initialize(self) -> None:
        with self.store.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS message_conversations (
                    account_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    peer_account_id TEXT,
                    peer_username TEXT,
                    peer_display_name TEXT,
                    last_message_id TEXT,
                    last_message_preview TEXT,
                    last_message_at TEXT,
                    unread_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, conversation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_message_conversations_updated
                    ON message_conversations(account_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS cached_messages (
                    account_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    conversation_id TEXT NOT NULL,
                    sender_account_id TEXT NOT NULL,
                    sender_display_name TEXT NOT NULL,
                    sender_pet_id TEXT,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (account_id, message_id),
                    FOREIGN KEY (account_id, conversation_id)
                        REFERENCES message_conversations(account_id, conversation_id)
                        ON DELETE CASCADE
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_cached_messages_sequence
                    ON cached_messages(account_id, conversation_id, sequence_number);
                CREATE TABLE IF NOT EXISTS cached_message_receipts (
                    local_account_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    receipt_account_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    delivered_at TEXT NOT NULL,
                    read_at TEXT,
                    PRIMARY KEY (local_account_id, message_id, receipt_account_id),
                    FOREIGN KEY (local_account_id, message_id)
                        REFERENCES cached_messages(account_id, message_id)
                        ON DELETE CASCADE
                );
                """
            )

    def upsert_conversation(self, conversation: ConversationRecord) -> None:
        last = conversation.last_message
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO message_conversations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id, conversation_id) DO UPDATE SET
                    kind=excluded.kind,
                    title=excluded.title,
                    peer_account_id=excluded.peer_account_id,
                    peer_username=excluded.peer_username,
                    peer_display_name=excluded.peer_display_name,
                    last_message_id=excluded.last_message_id,
                    last_message_preview=excluded.last_message_preview,
                    last_message_at=excluded.last_message_at,
                    unread_count=excluded.unread_count,
                    updated_at=excluded.updated_at
                """,
                (
                    conversation.account_id,
                    conversation.conversation_id,
                    conversation.kind,
                    conversation.title,
                    conversation.peer_account_id,
                    conversation.peer_username,
                    conversation.peer_display_name,
                    last.message_id if last else None,
                    last.content[:240] if last else None,
                    _iso(last.created_at, "last_message.created_at") if last else None,
                    max(0, int(conversation.unread_count)),
                    _iso(conversation.updated_at, "conversation.updated_at"),
                ),
            )
        if last is not None:
            self.upsert_message(last, is_read=last.outgoing or conversation.unread_count == 0)

    def get_conversation(
        self,
        account_id: str,
        conversation_id: str,
    ) -> ConversationRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM message_conversations
            WHERE account_id=? AND conversation_id=?
            """,
            (account_id, conversation_id),
        ).fetchone()
        return self._conversation(row) if row else None

    def list_conversations(self, account_id: str, limit: int = 100) -> list[ConversationRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM message_conversations
            WHERE account_id=? ORDER BY updated_at DESC, conversation_id LIMIT ?
            """,
            (account_id, max(1, min(500, int(limit)))),
        ).fetchall()
        return [self._conversation(row) for row in rows]

    def _conversation(self, row: sqlite3.Row) -> ConversationRecord:
        last = None
        if row["last_message_id"]:
            last_row = self._connection.execute(
                """
                SELECT * FROM cached_messages
                WHERE account_id=? AND message_id=?
                """,
                (row["account_id"], row["last_message_id"]),
            ).fetchone()
            if last_row:
                last = self._message(last_row)
        return ConversationRecord(
            account_id=row["account_id"],
            conversation_id=row["conversation_id"],
            kind=row["kind"],
            title=row["title"],
            peer_account_id=row["peer_account_id"],
            peer_username=row["peer_username"],
            peer_display_name=row["peer_display_name"],
            last_message=last,
            unread_count=int(row["unread_count"]),
            updated_at=_parse(row["updated_at"]) or datetime.now().astimezone(),
        )

    def upsert_message(self, message: MessageRecord, *, is_read: bool | None = None) -> None:
        existing = self._connection.execute(
            """
            SELECT is_read FROM cached_messages
            WHERE account_id=? AND message_id=?
            """,
            (message.account_id, message.message_id),
        ).fetchone()
        resolved_read = bool(existing["is_read"]) if existing and is_read is None else bool(is_read)
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO cached_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id, message_id) DO UPDATE SET
                    sequence_number=excluded.sequence_number,
                    conversation_id=excluded.conversation_id,
                    sender_account_id=excluded.sender_account_id,
                    sender_display_name=excluded.sender_display_name,
                    sender_pet_id=excluded.sender_pet_id,
                    message_type=excluded.message_type,
                    content=excluded.content,
                    created_at=excluded.created_at,
                    is_read=MAX(cached_messages.is_read, excluded.is_read)
                """,
                (
                    message.account_id,
                    message.message_id,
                    message.sequence_number,
                    message.conversation_id,
                    message.sender_account_id,
                    message.sender_display_name,
                    message.sender_pet_id,
                    message.message_type,
                    message.content,
                    _iso(message.created_at, "message.created_at"),
                    int(resolved_read or message.outgoing),
                ),
            )

    def list_messages(
        self,
        account_id: str,
        conversation_id: str,
        limit: int = 200,
    ) -> list[MessageRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM cached_messages
            WHERE account_id=? AND conversation_id=?
            ORDER BY sequence_number DESC LIMIT ?
            """,
            (account_id, conversation_id, max(1, min(1000, int(limit)))),
        ).fetchall()
        return [self._message(row) for row in reversed(rows)]

    @staticmethod
    def _message(row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            account_id=row["account_id"],
            message_id=row["message_id"],
            sequence_number=int(row["sequence_number"]),
            conversation_id=row["conversation_id"],
            sender_account_id=row["sender_account_id"],
            sender_display_name=row["sender_display_name"],
            sender_pet_id=row["sender_pet_id"],
            message_type=row["message_type"],
            content=row["content"],
            created_at=_parse(row["created_at"]) or datetime.now().astimezone(),
        )

    def latest_message(
        self,
        account_id: str,
        conversation_id: str,
    ) -> MessageRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM cached_messages
            WHERE account_id=? AND conversation_id=?
            ORDER BY sequence_number DESC LIMIT 1
            """,
            (account_id, conversation_id),
        ).fetchone()
        return self._message(row) if row else None

    def upsert_receipt(
        self,
        local_account_id: str,
        receipt: MessageReceiptRecord,
    ) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO cached_message_receipts VALUES (?,?,?,?,?,?)
                ON CONFLICT(local_account_id, message_id, receipt_account_id)
                DO UPDATE SET
                    state=CASE
                        WHEN cached_message_receipts.state='read' THEN 'read'
                        ELSE excluded.state
                    END,
                    delivered_at=excluded.delivered_at,
                    read_at=COALESCE(cached_message_receipts.read_at, excluded.read_at)
                """,
                (
                    local_account_id,
                    receipt.message_id,
                    receipt.account_id,
                    receipt.state,
                    _iso(receipt.delivered_at, "receipt.delivered_at"),
                    _iso(receipt.read_at, "receipt.read_at") if receipt.read_at else None,
                ),
            )

    def mark_read_through(
        self,
        account_id: str,
        conversation_id: str,
        sequence_number: int,
    ) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE cached_messages SET is_read=1
                WHERE account_id=? AND conversation_id=? AND sequence_number<=?
                """,
                (account_id, conversation_id, max(0, int(sequence_number))),
            )
            connection.execute(
                """
                UPDATE message_conversations SET unread_count=0
                WHERE account_id=? AND conversation_id=?
                """,
                (account_id, conversation_id),
            )
            connection.execute(
                """
                UPDATE folded_notifications SET is_read=1
                WHERE account_id=? AND kind='message' AND source_id=?
                """,
                (account_id, conversation_id),
            )

    def unread_count(self, account_id: str) -> int:
        row = self._connection.execute(
            """
            SELECT COALESCE(SUM(unread_count), 0) total
            FROM message_conversations WHERE account_id=?
            """,
            (account_id,),
        ).fetchone()
        return int(row["total"]) if row else 0
