"""MyPets PC 客户端本地 SQLite 状态仓库。

本模块只保存可重建的本地缓存和设备状态，不把 SQLite 作为云端权威数据源。所有
时间字段使用带时区的 ISO 8601；云同步使用幂等 outbox 和单调游标。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
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


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} 必须包含时区")
    return value


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class LocalStateStore:
    """保存宠物缓存、提醒、折叠通知和云同步状态。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), timeout=5.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if str(path) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._closed = False
        self.initialize()

    @classmethod
    def open_default(cls) -> "LocalStateStore":
        """打开用户数据目录中的默认数据库。"""

        return cls(local_state_path())

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """使用 SQLite 原子事务执行一组本地状态操作。"""

        with self._connection:
            yield self._connection

    def initialize(self) -> None:
        """幂等创建第一版本地缓存结构。"""

        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS local_schema (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pets (
                    pet_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    template_version TEXT NOT NULL,
                    identity_version TEXT NOT NULL,
                    primary_owner_account_id TEXT NOT NULL,
                    growth_stage TEXT NOT NULL,
                    growth_level INTEGER NOT NULL,
                    growth_exp INTEGER NOT NULL,
                    bond_level INTEGER NOT NULL,
                    bond_exp INTEGER NOT NULL,
                    hunger INTEGER NOT NULL,
                    energy INTEGER NOT NULL,
                    mood INTEGER NOT NULL,
                    cleanliness INTEGER NOT NULL,
                    health INTEGER NOT NULL,
                    boredom INTEGER NOT NULL,
                    state_version INTEGER NOT NULL,
                    presence TEXT NOT NULL,
                    personality_type TEXT NOT NULL,
                    asset_version TEXT NOT NULL,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS account_pet_relations (
                    account_id TEXT NOT NULL,
                    pet_id TEXT NOT NULL REFERENCES pets(pet_id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    affinity INTEGER NOT NULL,
                    care_contribution INTEGER NOT NULL,
                    PRIMARY KEY (account_id, pet_id)
                );

                CREATE TABLE IF NOT EXISTS device_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS folded_notifications (
                    notification_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    pet_id TEXT,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_notifications_account_created
                    ON folded_notifications(account_id, is_archived, created_at DESC);

                CREATE TABLE IF NOT EXISTS reminder_occurrences (
                    occurrence_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_reminder_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    category TEXT NOT NULL,
                    version INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_reminders_due
                    ON reminder_occurrences(account_id, state, scheduled_at);

                CREATE TABLE IF NOT EXISTS cloud_outbox (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    target_account_id TEXT NOT NULL,
                    target_device_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_cloud_outbox_sequence
                    ON cloud_outbox(sequence_number, created_at);

                CREATE TABLE IF NOT EXISTS cloud_cursors (
                    stream TEXT PRIMARY KEY,
                    sequence_number INTEGER NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO local_schema(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now().astimezone().isoformat()),
            )

    def close(self) -> None:
        """幂等关闭数据库连接。"""

        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def upsert_pet(self, profile: PetProfile) -> None:
        """按 pet_id 写入或替换宠物缓存快照。"""

        profile.normalize()
        identity = profile.identity
        stats = profile.stats
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO pets (
                    pet_id, name, template_id, template_version, identity_version,
                    primary_owner_account_id, growth_stage, growth_level, growth_exp,
                    bond_level, bond_exp, hunger, energy, mood, cleanliness, health,
                    boredom, state_version, presence, personality_type, asset_version,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pet_id) DO UPDATE SET
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
                (
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
                    profile.updated_at.isoformat() if profile.updated_at else None,
                ),
            )

    def get_pet(self, pet_id: str) -> PetProfile | None:
        """按稳定宠物标识读取缓存。"""

        row = self._connection.execute(
            "SELECT * FROM pets WHERE pet_id = ?", (pet_id,)
        ).fetchone()
        return self._pet_from_row(row) if row is not None else None

    def list_pets(self) -> list[PetProfile]:
        """返回当前设备缓存的全部宠物。"""

        rows = self._connection.execute(
            "SELECT * FROM pets ORDER BY name COLLATE NOCASE, pet_id"
        ).fetchall()
        return [self._pet_from_row(row) for row in rows]

    def delete_pet(self, pet_id: str) -> None:
        """删除本地缓存，并清除失效的当前宠物选择。"""

        with self.transaction() as connection:
            connection.execute("DELETE FROM pets WHERE pet_id = ?", (pet_id,))
            connection.execute(
                "DELETE FROM device_state WHERE key = 'active_pet_id' AND value = ?",
                (pet_id,),
            )

    @staticmethod
    def _pet_from_row(row: sqlite3.Row) -> PetProfile:
        return PetProfile(
            identity=PetIdentity(
                pet_id=row["pet_id"],
                name=row["name"],
                template_id=row["template_id"],
                template_version=row["template_version"],
                identity_version=row["identity_version"],
                primary_owner_account_id=row["primary_owner_account_id"],
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
            updated_at=_parse_datetime(row["updated_at"]),
        )

    def set_active_pet_id(self, pet_id: str | None) -> None:
        """保存本设备当前显示的宠物。"""

        with self.transaction() as connection:
            if pet_id is None:
                connection.execute("DELETE FROM device_state WHERE key = 'active_pet_id'")
                return
            if self.get_pet(pet_id) is None:
                raise KeyError(f"本地不存在宠物：{pet_id}")
            connection.execute(
                """
                INSERT INTO device_state(key, value) VALUES ('active_pet_id', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (pet_id,),
            )

    def get_active_pet_id(self) -> str | None:
        """读取本设备当前宠物标识。"""

        row = self._connection.execute(
            "SELECT value FROM device_state WHERE key = 'active_pet_id'"
        ).fetchone()
        return str(row["value"]) if row is not None else None

    def upsert_relation(self, relation: AccountPetRelation) -> None:
        """保存账户对宠物的照料角色与关系数值。"""

        if self.get_pet(relation.pet_id) is None:
            raise KeyError(f"本地不存在宠物：{relation.pet_id}")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO account_pet_relations(
                    account_id, pet_id, role, affinity, care_contribution
                ) VALUES (?, ?, ?, ?, ?)
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

    def list_relations(self, pet_id: str | None = None) -> list[AccountPetRelation]:
        """列出全部关系或指定宠物的照料成员。"""

        if pet_id is None:
            rows = self._connection.execute(
                "SELECT * FROM account_pet_relations ORDER BY pet_id, account_id"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM account_pet_relations WHERE pet_id = ? ORDER BY account_id",
                (pet_id,),
            ).fetchall()
        return [
            AccountPetRelation(
                account_id=row["account_id"],
                pet_id=row["pet_id"],
                role=PetRole(row["role"]),
                affinity=row["affinity"],
                care_contribution=row["care_contribution"],
            )
            for row in rows
        ]

    def put_notification(self, notification: FoldedNotification) -> None:
        """幂等写入一条低打扰折叠通知。"""

        created_at = _require_aware(notification.created_at, "created_at")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO folded_notifications(
                    notification_id, account_id, pet_id, kind, title, body,
                    source_id, created_at, is_read, is_archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                (
                    notification.notification_id,
                    notification.account_id,
                    notification.pet_id,
                    notification.kind.value,
                    notification.title,
                    notification.body,
                    notification.source_id,
                    created_at.isoformat(),
                    int(notification.is_read),
                    int(notification.is_archived),
                ),
            )

    def list_notifications(
        self,
        account_id: str,
        *,
        unread_only: bool = False,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[FoldedNotification]:
        """按时间倒序读取折叠通知。"""

        conditions = ["account_id = ?"]
        parameters: list[object] = [account_id]
        if unread_only:
            conditions.append("is_read = 0")
        if not include_archived:
            conditions.append("is_archived = 0")
        parameters.append(max(1, min(1000, int(limit))))
        rows = self._connection.execute(
            f"""
            SELECT * FROM folded_notifications
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC, notification_id
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [self._notification_from_row(row) for row in rows]

    @staticmethod
    def _notification_from_row(row: sqlite3.Row) -> FoldedNotification:
        return FoldedNotification(
            notification_id=row["notification_id"],
            account_id=row["account_id"],
            pet_id=row["pet_id"],
            kind=NotificationKind(row["kind"]),
            title=row["title"],
            body=row["body"],
            source_id=row["source_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            is_read=bool(row["is_read"]),
            is_archived=bool(row["is_archived"]),
        )

    def unread_counts(self, account_id: str) -> dict[NotificationKind, int]:
        """分别统计消息、提醒和其他通知，避免混为一个已读状态。"""

        rows = self._connection.execute(
            """
            SELECT kind, COUNT(*) AS total
            FROM folded_notifications
            WHERE account_id = ? AND is_read = 0 AND is_archived = 0
            GROUP BY kind
            """,
            (account_id,),
        ).fetchall()
        return {NotificationKind(row["kind"]): int(row["total"]) for row in rows}

    def mark_notification_read(self, notification_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE folded_notifications SET is_read = 1 WHERE notification_id = ?",
                (notification_id,),
            )

    def archive_notification(self, notification_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE folded_notifications
                SET is_read = 1, is_archived = 1
                WHERE notification_id = ?
                """,
                (notification_id,),
            )

    def put_reminder(self, occurrence: ReminderOccurrence) -> None:
        """按版本幂等写入一次具体提醒；旧版本不得覆盖新版本。"""

        scheduled_at = _require_aware(occurrence.scheduled_at, "scheduled_at")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO reminder_occurrences(
                    occurrence_id, source, source_reminder_id, account_id, title,
                    content, scheduled_at, timezone, state, priority, category, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                (
                    occurrence.occurrence_id,
                    occurrence.source,
                    occurrence.source_reminder_id,
                    occurrence.account_id,
                    occurrence.title,
                    occurrence.content,
                    scheduled_at.isoformat(),
                    occurrence.timezone,
                    occurrence.state.value,
                    occurrence.priority,
                    occurrence.category,
                    occurrence.version,
                ),
            )

    def list_due_reminders(
        self,
        account_id: str,
        now: datetime,
        limit: int = 100,
    ) -> list[ReminderOccurrence]:
        """返回到期且尚未领取的提醒实例。"""

        now = _require_aware(now, "now")
        rows = self._connection.execute(
            """
            SELECT * FROM reminder_occurrences
            WHERE account_id = ? AND state = ? AND scheduled_at <= ?
            ORDER BY scheduled_at, occurrence_id
            LIMIT ?
            """,
            (
                account_id,
                ReminderOccurrenceState.PENDING.value,
                now.isoformat(),
                max(1, min(1000, int(limit))),
            ),
        ).fetchall()
        return [self._reminder_from_row(row) for row in rows]

    @staticmethod
    def _reminder_from_row(row: sqlite3.Row) -> ReminderOccurrence:
        return ReminderOccurrence(
            occurrence_id=row["occurrence_id"],
            source=row["source"],
            source_reminder_id=row["source_reminder_id"],
            account_id=row["account_id"],
            title=row["title"],
            content=row["content"],
            scheduled_at=datetime.fromisoformat(row["scheduled_at"]),
            timezone=row["timezone"],
            state=ReminderOccurrenceState(row["state"]),
            priority=row["priority"],
            category=row["category"],
            version=row["version"],
        )

    def set_reminder_state(
        self,
        occurrence_id: str,
        state: ReminderOccurrenceState,
    ) -> None:
        """更新提醒实例状态；具体状态迁移规则由应用服务执行。"""

        with self.transaction() as connection:
            connection.execute(
                "UPDATE reminder_occurrences SET state = ? WHERE occurrence_id = ?",
                (state.value, occurrence_id),
            )

    def enqueue_event(self, event: CloudEvent) -> bool:
        """写入待上传语义事件；重复幂等键返回 False。"""

        created_at = _require_aware(event.created_at, "created_at")
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO cloud_outbox(
                    event_id, event_type, sequence_number, idempotency_key, created_at,
                    payload_json, target_account_id, target_device_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.sequence_number,
                    event.idempotency_key,
                    created_at.isoformat(),
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
        """按服务端语义序号读取待上传事件。"""

        rows = self._connection.execute(
            """
            SELECT * FROM cloud_outbox
            ORDER BY sequence_number, created_at, event_id
            LIMIT ?
            """,
            (max(1, min(1000, int(limit))),),
        ).fetchall()
        return [
            CloudEvent(
                event_id=row["event_id"],
                event_type=row["event_type"],
                sequence_number=row["sequence_number"],
                idempotency_key=row["idempotency_key"],
                created_at=datetime.fromisoformat(row["created_at"]),
                payload=json.loads(row["payload_json"]),
                target_account_id=row["target_account_id"],
                target_device_id=row["target_device_id"],
            )
            for row in rows
        ]

    def acknowledge_event(self, event_id: str) -> None:
        """服务端确认事件后从 outbox 删除。"""

        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM cloud_outbox WHERE event_id = ?",
                (event_id,),
            )

    def set_cursor(self, stream: str, sequence_number: int) -> None:
        """保存单调递增的云事件消费游标。"""

        stream = stream.strip()
        if not stream:
            raise ValueError("stream 不能为空")
        sequence_number = max(0, int(sequence_number))
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO cloud_cursors(stream, sequence_number) VALUES (?, ?)
                ON CONFLICT(stream) DO UPDATE SET sequence_number = CASE
                    WHEN excluded.sequence_number > cloud_cursors.sequence_number
                    THEN excluded.sequence_number
                    ELSE cloud_cursors.sequence_number
                END
                """,
                (stream, sequence_number),
            )

    def get_cursor(self, stream: str) -> int:
        """读取指定实时或增量同步流的最后序号。"""

        row = self._connection.execute(
            "SELECT sequence_number FROM cloud_cursors WHERE stream = ?",
            (stream,),
        ).fetchone()
        return int(row["sequence_number"]) if row is not None else 0
