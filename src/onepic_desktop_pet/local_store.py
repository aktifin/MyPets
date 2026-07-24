"""MyPets PC 客户端本地 SQLite 缓存与同步状态仓库。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .config import user_data_dir
from .domain import (
    AccountPetRelation,
    CloudEvent,
    FoldedNotification,
    GrowthStage,
    NotificationKind,
    PetIdentity,
    PetProfile,
    PetRole,
    PetStats,
    PresenceStatus,
    ReminderOccurrence,
    ReminderOccurrenceState,
)

SCHEMA_VERSION = 1


def local_state_path() -> Path:
    """返回当前设备的本地状态数据库路径。"""

    return user_data_dir() / "state.sqlite3"


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} 必须包含时区")
    return value.astimezone(UTC)


def _iso(value: datetime, field_name: str) -> str:
    return _utc(value, field_name).isoformat()


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class LocalStateStore:
    """保存可重建缓存；云端仍是宠物业务状态的权威来源。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._memory = str(path) == ":memory:"
        if not self._memory:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), timeout=5.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if not self._memory:
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._closed = False
        self.initialize()

    @classmethod
    def open_default(cls) -> "LocalStateStore":
        return cls(local_state_path())

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection:
            yield self._connection

    def initialize(self) -> None:
        """幂等建立本地缓存结构。"""

        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS local_schema (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pets (
                    pet_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    template_id TEXT NOT NULL, template_version TEXT NOT NULL,
                    identity_version TEXT NOT NULL,
                    primary_owner_account_id TEXT NOT NULL,
                    growth_stage TEXT NOT NULL, growth_level INTEGER NOT NULL,
                    growth_exp INTEGER NOT NULL, bond_level INTEGER NOT NULL,
                    bond_exp INTEGER NOT NULL, hunger INTEGER NOT NULL,
                    energy INTEGER NOT NULL, mood INTEGER NOT NULL,
                    cleanliness INTEGER NOT NULL, health INTEGER NOT NULL,
                    boredom INTEGER NOT NULL, state_version INTEGER NOT NULL,
                    presence TEXT NOT NULL, personality_type TEXT NOT NULL,
                    asset_version TEXT NOT NULL, updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS account_pet_relations (
                    account_id TEXT NOT NULL,
                    pet_id TEXT NOT NULL REFERENCES pets(pet_id) ON DELETE CASCADE,
                    role TEXT NOT NULL, affinity INTEGER NOT NULL,
                    care_contribution INTEGER NOT NULL,
                    PRIMARY KEY (account_id, pet_id)
                );
                CREATE TABLE IF NOT EXISTS device_state (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS folded_notifications (
                    notification_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    pet_id TEXT, kind TEXT NOT NULL, title TEXT NOT NULL,
                    body TEXT NOT NULL, source_id TEXT, created_at TEXT NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_account_created
                    ON folded_notifications(account_id, is_archived, created_at DESC);
                CREATE TABLE IF NOT EXISTS reminder_occurrences (
                    occurrence_id TEXT PRIMARY KEY, source TEXT NOT NULL,
                    source_reminder_id TEXT NOT NULL, account_id TEXT NOT NULL,
                    title TEXT NOT NULL, content TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL, timezone TEXT NOT NULL,
                    state TEXT NOT NULL, priority TEXT NOT NULL,
                    category TEXT NOT NULL, version INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reminders_due
                    ON reminder_occurrences(account_id, state, scheduled_at);
                CREATE TABLE IF NOT EXISTS cloud_outbox (
                    event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                    target_account_id TEXT NOT NULL, target_device_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_cloud_outbox_sequence
                    ON cloud_outbox(sequence_number, created_at);
                CREATE TABLE IF NOT EXISTS cloud_cursors (
                    stream TEXT PRIMARY KEY, sequence_number INTEGER NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO local_schema VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
            )

    def close(self) -> None:
        """幂等关闭数据库连接。"""

        if not self._closed:
            self._connection.close()
            self._closed = True

    def upsert_pet(self, profile: PetProfile) -> None:
        """按稳定宠物标识写入完整缓存快照。"""

        profile.normalize()
        identity, stats = profile.identity, profile.stats
        updated_at = (
            _iso(profile.updated_at, "updated_at")
            if profile.updated_at
            else None
        )
        values = (
            identity.pet_id,
            identity.name,
            identity.template_id,
            identity.template_version,
            identity.identity_version,
            identity.primary_owner_account_id,
            stats.growth_stage.value,
            stats.growth_level,
            stats.growth_exp,
            stats.bond_level,
            stats.bond_exp,
            stats.hunger,
            stats.energy,
            stats.mood,
            stats.cleanliness,
            stats.health,
            stats.boredom,
            stats.state_version,
            profile.presence.value,
            profile.personality_type,
            profile.asset_version,
            updated_at,
        )
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO pets VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                ) ON CONFLICT(pet_id) DO UPDATE SET
                    name=excluded.name,
                    template_id=excluded.template_id,
                    template_version=excluded.template_version,
                    identity_version=excluded.identity_version,
                    primary_owner_account_id=excluded.primary_owner_account_id,
                    growth_stage=excluded.growth_stage,
                    growth_level=excluded.growth_level,
                    growth_exp=excluded.growth_exp,
                    bond_level=excluded.bond_level,
                    bond_exp=excluded.bond_exp,
                    hunger=excluded.hunger,
                    energy=excluded.energy,
                    mood=excluded.mood,
                    cleanliness=excluded.cleanliness,
                    health=excluded.health,
                    boredom=excluded.boredom,
                    state_version=excluded.state_version,
                    presence=excluded.presence,
                    personality_type=excluded.personality_type,
                    asset_version=excluded.asset_version,
                    updated_at=excluded.updated_at
                """,
                values,
            )

    def get_pet(self, pet_id: str) -> PetProfile | None:
        row = self._connection.execute(
            "SELECT * FROM pets WHERE pet_id = ?",
            (pet_id,),
        ).fetchone()
        return self._pet(row) if row else None

    def list_pets(self) -> list[PetProfile]:
        rows = self._connection.execute(
            "SELECT * FROM pets ORDER BY name COLLATE NOCASE, pet_id"
        ).fetchall()
        return [self._pet(row) for row in rows]

    def delete_pet(self, pet_id: str) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM pets WHERE pet_id = ?", (pet_id,))
            connection.execute(
                "DELETE FROM device_state WHERE key='active_pet_id' AND value=?",
                (pet_id,),
            )

    @staticmethod
    def _pet(row: sqlite3.Row) -> PetProfile:
        return PetProfile(
            identity=PetIdentity(
                row["pet_id"],
                row["name"],
                row["template_id"],
                row["template_version"],
                row["identity_version"],
                row["primary_owner_account_id"],
            ),
            stats=PetStats(
                growth_stage=GrowthStage(row["growth_stage"]),
                growth_level=row["growth_level"],
                growth_exp=row["growth_exp"],
                bond_level=row["bond_level"],
                bond_exp=row["bond_exp"],
                hunger=row["hunger"],
                energy=row["energy"],
                mood=row["mood"],
                cleanliness=row["cleanliness"],
                health=row["health"],
                boredom=row["boredom"],
                state_version=row["state_version"],
            ),
            presence=PresenceStatus(row["presence"]),
            personality_type=row["personality_type"],
            asset_version=row["asset_version"],
            updated_at=_parse(row["updated_at"]),
        )

    def set_active_pet_id(self, pet_id: str | None) -> None:
        with self.transaction() as connection:
            if pet_id is None:
                connection.execute(
                    "DELETE FROM device_state WHERE key='active_pet_id'"
                )
                return
            if self.get_pet(pet_id) is None:
                raise KeyError(f"本地不存在宠物：{pet_id}")
            connection.execute(
                """
                INSERT INTO device_state VALUES ('active_pet_id', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (pet_id,),
            )

    def get_active_pet_id(self) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM device_state WHERE key='active_pet_id'"
        ).fetchone()
        return str(row["value"]) if row else None

    def upsert_relation(self, relation: AccountPetRelation) -> None:
        if self.get_pet(relation.pet_id) is None:
            raise KeyError(f"本地不存在宠物：{relation.pet_id}")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO account_pet_relations VALUES (?,?,?,?,?)
                ON CONFLICT(account_id, pet_id) DO UPDATE SET
                    role=excluded.role,
                    affinity=excluded.affinity,
                    care_contribution=excluded.care_contribution
                """,
                (
                    relation.account_id,
                    relation.pet_id,
                    relation.role.value,
                    relation.affinity,
                    relation.care_contribution,
                ),
            )

    def list_relations(
        self,
        pet_id: str | None = None,
    ) -> list[AccountPetRelation]:
        if pet_id is None:
            rows = self._connection.execute(
                "SELECT * FROM account_pet_relations ORDER BY pet_id, account_id"
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM account_pet_relations
                WHERE pet_id=? ORDER BY account_id
                """,
                (pet_id,),
            ).fetchall()
        return [
            AccountPetRelation(
                row["account_id"],
                row["pet_id"],
                PetRole(row["role"]),
                row["affinity"],
                row["care_contribution"],
            )
            for row in rows
        ]

    def put_notification(self, notification: FoldedNotification) -> None:
        values = (
            notification.notification_id,
            notification.account_id,
            notification.pet_id,
            notification.kind.value,
            notification.title,
            notification.body,
            notification.source_id,
            _iso(notification.created_at, "created_at"),
            int(notification.is_read),
            int(notification.is_archived),
        )
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO folded_notifications VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(notification_id) DO UPDATE SET
                    account_id=excluded.account_id,
                    pet_id=excluded.pet_id,
                    kind=excluded.kind,
                    title=excluded.title,
                    body=excluded.body,
                    source_id=excluded.source_id,
                    created_at=excluded.created_at,
                    is_read=excluded.is_read,
                    is_archived=excluded.is_archived
                """,
                values,
            )

    def list_notifications(
        self,
        account_id: str,
        *,
        unread_only: bool = False,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[FoldedNotification]:
        conditions = ["account_id=?"]
        parameters: list[object] = [account_id]
        if unread_only:
            conditions.append("is_read=0")
        if not include_archived:
            conditions.append("is_archived=0")
        parameters.append(max(1, min(1000, int(limit))))
        rows = self._connection.execute(
            f"SELECT * FROM folded_notifications WHERE {' AND '.join(conditions)} "
            "ORDER BY created_at DESC, notification_id LIMIT ?",
            parameters,
        ).fetchall()
        return [self._notification(row) for row in rows]

    @staticmethod
    def _notification(row: sqlite3.Row) -> FoldedNotification:
        return FoldedNotification(
            row["notification_id"],
            row["account_id"],
            NotificationKind(row["kind"]),
            row["title"],
            row["body"],
            datetime.fromisoformat(row["created_at"]),
            row["pet_id"],
            row["source_id"],
            bool(row["is_read"]),
            bool(row["is_archived"]),
        )

    def unread_counts(self, account_id: str) -> dict[NotificationKind, int]:
        rows = self._connection.execute(
            """
            SELECT kind, COUNT(*) total FROM folded_notifications
            WHERE account_id=? AND is_read=0 AND is_archived=0
            GROUP BY kind
            """,
            (account_id,),
        ).fetchall()
        return {
            NotificationKind(row["kind"]): int(row["total"])
            for row in rows
        }

    def mark_notification_read(self, notification_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE folded_notifications SET is_read=1
                WHERE notification_id=?
                """,
                (notification_id,),
            )

    def archive_notification(self, notification_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE folded_notifications SET is_read=1, is_archived=1
                WHERE notification_id=?
                """,
                (notification_id,),
            )

    def put_reminder(self, occurrence: ReminderOccurrence) -> None:
        values = (
            occurrence.occurrence_id,
            occurrence.source,
            occurrence.source_reminder_id,
            occurrence.account_id,
            occurrence.title,
            occurrence.content,
            _iso(occurrence.scheduled_at, "scheduled_at"),
            occurrence.timezone,
            occurrence.state.value,
            occurrence.priority,
            occurrence.category,
            occurrence.version,
        )
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO reminder_occurrences VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(occurrence_id) DO UPDATE SET
                    source=excluded.source,
                    source_reminder_id=excluded.source_reminder_id,
                    account_id=excluded.account_id,
                    title=excluded.title,
                    content=excluded.content,
                    scheduled_at=excluded.scheduled_at,
                    timezone=excluded.timezone,
                    state=excluded.state,
                    priority=excluded.priority,
                    category=excluded.category,
                    version=excluded.version
                WHERE excluded.version >= reminder_occurrences.version
                """,
                values,
            )

    def list_due_reminders(
        self,
        account_id: str,
        now: datetime,
        limit: int = 100,
    ) -> list[ReminderOccurrence]:
        rows = self._connection.execute(
            """
            SELECT * FROM reminder_occurrences
            WHERE account_id=? AND state=? AND scheduled_at<=?
            ORDER BY scheduled_at, occurrence_id LIMIT ?
            """,
            (
                account_id,
                ReminderOccurrenceState.PENDING.value,
                _iso(now, "now"),
                max(1, min(1000, int(limit))),
            ),
        ).fetchall()
        return [self._reminder(row) for row in rows]

    @staticmethod
    def _reminder(row: sqlite3.Row) -> ReminderOccurrence:
        return ReminderOccurrence(
            row["occurrence_id"],
            row["source"],
            row["source_reminder_id"],
            row["account_id"],
            row["title"],
            row["content"],
            datetime.fromisoformat(row["scheduled_at"]),
            row["timezone"],
            ReminderOccurrenceState(row["state"]),
            row["priority"],
            row["category"],
            row["version"],
        )

    def set_reminder_state(
        self,
        occurrence_id: str,
        state: ReminderOccurrenceState,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE reminder_occurrences SET state=? WHERE occurrence_id=?",
                (state.value, occurrence_id),
            )

    def enqueue_event(self, event: CloudEvent) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO cloud_outbox VALUES (?,?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.event_type,
                    event.sequence_number,
                    event.idempotency_key,
                    _iso(event.created_at, "created_at"),
                    json.dumps(
                        event.payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    event.target_account_id,
                    event.target_device_id,
                ),
            )
            return cursor.rowcount > 0

    def pending_events(self, limit: int = 100) -> list[CloudEvent]:
        rows = self._connection.execute(
            """
            SELECT * FROM cloud_outbox
            ORDER BY sequence_number, created_at, event_id LIMIT ?
            """,
            (max(1, min(1000, int(limit))),),
        ).fetchall()
        return [
            CloudEvent(
                row["event_id"],
                row["event_type"],
                row["sequence_number"],
                row["idempotency_key"],
                datetime.fromisoformat(row["created_at"]),
                json.loads(row["payload_json"]),
                row["target_account_id"],
                row["target_device_id"],
            )
            for row in rows
        ]

    def acknowledge_event(self, event_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM cloud_outbox WHERE event_id=?",
                (event_id,),
            )

    def set_cursor(self, stream: str, sequence_number: int) -> None:
        stream = stream.strip()
        if not stream:
            raise ValueError("stream 不能为空")
        sequence_number = max(0, int(sequence_number))
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO cloud_cursors VALUES (?,?)
                ON CONFLICT(stream) DO UPDATE SET sequence_number=CASE
                    WHEN excluded.sequence_number > cloud_cursors.sequence_number
                    THEN excluded.sequence_number
                    ELSE cloud_cursors.sequence_number
                END
                """,
                (stream, sequence_number),
            )

    def get_cursor(self, stream: str) -> int:
        row = self._connection.execute(
            "SELECT sequence_number FROM cloud_cursors WHERE stream=?",
            (stream,),
        ).fetchone()
        return int(row["sequence_number"]) if row else 0
