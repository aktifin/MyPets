"""Account-scoped reminder cache and durable mutation outbox."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from .domain import ReminderOccurrence, ReminderOccurrenceState
from .local_store import LocalStateStore, _iso


@dataclass(frozen=True)
class ReminderCommand:
    command_id: str
    account_id: str
    occurrence_id: str
    action: str
    snooze_minutes: int | None
    idempotency_key: str
    created_at: datetime


class ReminderCache:
    """Wrap the existing SQLite connection with reminder-specific queries and outbox state."""

    def __init__(self, store: LocalStateStore) -> None:
        self.store = store
        self._connection = store._connection
        self.initialize()

    def initialize(self) -> None:
        with self.store.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS reminder_command_outbox (
                    command_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    occurrence_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    snooze_minutes INTEGER,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reminder_command_account_created
                    ON reminder_command_outbox(account_id, created_at, command_id);
                """
            )

    def put(self, occurrence: ReminderOccurrence) -> None:
        self.store.put_reminder(occurrence)

    def get(self, occurrence_id: str) -> ReminderOccurrence | None:
        row = self._connection.execute(
            "SELECT * FROM reminder_occurrences WHERE occurrence_id=?",
            (occurrence_id,),
        ).fetchone()
        return self.store._reminder(row) if row else None

    def list_for_account(
        self,
        account_id: str,
        *,
        states: set[ReminderOccurrenceState] | None = None,
        limit: int = 500,
    ) -> list[ReminderOccurrence]:
        parameters: list[object] = [account_id]
        conditions = ["account_id=?"]
        if states:
            placeholders = ",".join("?" for _ in states)
            conditions.append(f"state IN ({placeholders})")
            parameters.extend(state.value for state in sorted(states, key=lambda item: item.value))
        parameters.append(max(1, min(1000, int(limit))))
        rows = self._connection.execute(
            f"SELECT * FROM reminder_occurrences WHERE {' AND '.join(conditions)} "
            "ORDER BY scheduled_at, occurrence_id LIMIT ?",
            parameters,
        ).fetchall()
        return [self.store._reminder(row) for row in rows]

    def due(self, account_id: str, now: datetime, limit: int = 100) -> list[ReminderOccurrence]:
        return self.store.list_due_reminders(account_id, now, limit)

    def mark_delivered(self, occurrence_id: str) -> None:
        self.store.set_reminder_state(occurrence_id, ReminderOccurrenceState.DELIVERED)

    def complete_locally(self, occurrence_id: str) -> ReminderOccurrence:
        occurrence = self._require(occurrence_id)
        self.store.set_reminder_state(occurrence_id, ReminderOccurrenceState.COMPLETED)
        self._archive_notification(occurrence.account_id, occurrence_id)
        return self._require(occurrence_id)

    def snooze_locally(
        self,
        occurrence_id: str,
        minutes: int,
        *,
        now: datetime,
    ) -> ReminderOccurrence:
        if minutes not in {5, 10, 30}:
            raise ValueError("只支持 5、10 或 30 分钟贪睡")
        if now.tzinfo is None:
            raise ValueError("now 必须包含时区")
        occurrence = self._require(occurrence_id)
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE reminder_occurrences
                SET state=?, scheduled_at=?, version=?
                WHERE occurrence_id=?
                """,
                (
                    ReminderOccurrenceState.PENDING.value,
                    _iso(now + timedelta(minutes=minutes), "scheduled_at"),
                    occurrence.version + 1,
                    occurrence_id,
                ),
            )
        self._archive_notification(occurrence.account_id, occurrence_id)
        return self._require(occurrence_id)

    def dismiss_locally(self, occurrence_id: str) -> ReminderOccurrence:
        occurrence = self._require(occurrence_id)
        self.store.set_reminder_state(occurrence_id, ReminderOccurrenceState.DISMISSED)
        self._archive_notification(occurrence.account_id, occurrence_id)
        return self._require(occurrence_id)

    def archive_notification(self, account_id: str, occurrence_id: str) -> None:
        self._archive_notification(account_id, occurrence_id)

    def _archive_notification(self, account_id: str, occurrence_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE folded_notifications SET is_read=1, is_archived=1
                WHERE account_id=? AND kind='reminder' AND source_id=?
                """,
                (account_id, occurrence_id),
            )

    def enqueue(
        self,
        *,
        account_id: str,
        occurrence_id: str,
        action: str,
        snooze_minutes: int | None = None,
        idempotency_key: str | None = None,
    ) -> ReminderCommand:
        normalized_action = action.strip().lower()
        if normalized_action not in {"delivered", "completed", "snoozed", "dismissed"}:
            raise ValueError("不支持的提醒命令")
        if normalized_action == "snoozed" and snooze_minutes not in {5, 10, 30}:
            raise ValueError("贪睡命令分钟数无效")
        if normalized_action != "snoozed":
            snooze_minutes = None
        now = datetime.now().astimezone()
        command = ReminderCommand(
            command_id=str(uuid4()),
            account_id=account_id,
            occurrence_id=occurrence_id,
            action=normalized_action,
            snooze_minutes=snooze_minutes,
            idempotency_key=idempotency_key
            or f"desktop-reminder-{normalized_action}-{uuid4()}",
            created_at=now,
        )
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO reminder_command_outbox VALUES (?,?,?,?,?,?,?)
                """,
                (
                    command.command_id,
                    command.account_id,
                    command.occurrence_id,
                    command.action,
                    command.snooze_minutes,
                    command.idempotency_key,
                    _iso(command.created_at, "created_at"),
                ),
            )
        return command

    def pending_commands(self, account_id: str, limit: int = 100) -> list[ReminderCommand]:
        rows = self._connection.execute(
            """
            SELECT * FROM reminder_command_outbox
            WHERE account_id=? ORDER BY created_at, command_id LIMIT ?
            """,
            (account_id, max(1, min(500, int(limit)))),
        ).fetchall()
        return [self._command(row) for row in rows]

    @staticmethod
    def _command(row: sqlite3.Row) -> ReminderCommand:
        return ReminderCommand(
            command_id=row["command_id"],
            account_id=row["account_id"],
            occurrence_id=row["occurrence_id"],
            action=row["action"],
            snooze_minutes=row["snooze_minutes"],
            idempotency_key=row["idempotency_key"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def acknowledge(self, command_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                "DELETE FROM reminder_command_outbox WHERE command_id=?",
                (command_id,),
            )

    def _require(self, occurrence_id: str) -> ReminderOccurrence:
        occurrence = self.get(occurrence_id)
        if occurrence is None:
            raise KeyError(f"本地不存在提醒实例：{occurrence_id}")
        return occurrence
