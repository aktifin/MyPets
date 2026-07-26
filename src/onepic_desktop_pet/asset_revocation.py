"""Durable revoked-asset eviction, safe fallback policy, and device acknowledgements.

This module is installed by ``asset_download`` before the desktop application creates its
cloud session. The integration deliberately keeps synchronization, cache policy, and network
transport separated while preserving crash-safe local tasks.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .config import user_data_dir
from .pet_assets import PetAssetIdentity, PetAssetSelection, _slug


@dataclass(frozen=True)
class AssetRevocationTask:
    right_id: str
    artifact_id: str
    pet_id: str
    release_id: str
    template_id: str
    identity_version: str
    asset_version: str
    reason: str
    status: str
    cache_cleared: bool
    fallback_applied: bool
    message: str
    processed_at: datetime | None
    acknowledged_at: datetime | None

    @property
    def identity(self) -> PetAssetIdentity:
        return PetAssetIdentity(
            self.template_id,
            self.identity_version,
            self.asset_version,
        )

    @property
    def key(self) -> tuple[str, str]:
        return self.right_id, self.release_id


class AssetRevocationTaskStore:
    """Persist revocation work before the sync cursor is advanced."""

    def __init__(self, local_store) -> None:
        self.local_store = local_store
        self._ensure_table()

    def _ensure_table(self) -> None:
        with self.local_store.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS asset_revocation_tasks (
                    right_id TEXT NOT NULL,
                    release_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    pet_id TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    identity_version TEXT NOT NULL,
                    asset_version TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    cache_cleared INTEGER NOT NULL DEFAULT 0,
                    fallback_applied INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    process_attempts INTEGER NOT NULL DEFAULT 0,
                    received_at TEXT NOT NULL,
                    processed_at TEXT,
                    acknowledged_at TEXT,
                    PRIMARY KEY (right_id, release_id)
                );
                CREATE INDEX IF NOT EXISTS idx_asset_revocation_tasks_pending
                    ON asset_revocation_tasks(status, acknowledged_at, received_at);
                """
            )

    @staticmethod
    def _required(data: Mapping[str, Any], name: str) -> str:
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"撤销事件缺少 {name}")
        return value.strip()

    def queue_from_sync_payload(self, payload: Mapping[str, Any]) -> int:
        events = payload.get("events")
        if not isinstance(events, list):
            return 0
        queued = 0
        for raw_event in events:
            if not isinstance(raw_event, dict) or raw_event.get("event_type") != "asset_revoked":
                continue
            event_payload = raw_event.get("payload")
            if not isinstance(event_payload, dict):
                raise ValueError("撤销事件 payload 必须是对象")
            if event_payload.get("action") != "evict_cache_and_fallback":
                raise ValueError("撤销事件动作无效")
            right_id = self._required(event_payload, "right_id")
            release_id = self._required(event_payload, "release_id")
            artifact_id = self._required(event_payload, "artifact_id")
            pet_id = self._required(event_payload, "pet_id")
            reason = self._required(event_payload, "reason")
            event_id = self._required(raw_event, "event_id")

            identity_payload = event_payload.get("asset_identity")
            if isinstance(identity_payload, dict):
                template_id = self._required(identity_payload, "template_id")
                identity_version = self._required(identity_payload, "identity_version")
                asset_version = self._required(identity_payload, "asset_version")
            else:
                pet = self.local_store.get_pet(pet_id)
                if pet is None:
                    raise ValueError("撤销事件引用的宠物不在本地缓存中")
                template_id = pet.identity.template_id
                identity_version = pet.identity.identity_version
                asset_version = pet.asset_version

            now = datetime.now(UTC).isoformat()
            with self.local_store.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO asset_revocation_tasks (
                        right_id, release_id, artifact_id, pet_id,
                        template_id, identity_version, asset_version,
                        reason, event_id, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        right_id,
                        release_id,
                        artifact_id,
                        pet_id,
                        template_id,
                        identity_version,
                        asset_version,
                        reason,
                        event_id,
                        now,
                    ),
                )
                queued += max(0, cursor.rowcount)
        return queued

    def list_processable(self) -> list[AssetRevocationTask]:
        rows = self.local_store._connection.execute(
            """
            SELECT * FROM asset_revocation_tasks
            WHERE status IN ('pending', 'failed')
            ORDER BY received_at, right_id, release_id
            """
        ).fetchall()
        return [self._task(row) for row in rows]

    def list_unacknowledged(self) -> list[AssetRevocationTask]:
        rows = self.local_store._connection.execute(
            """
            SELECT * FROM asset_revocation_tasks
            WHERE status IN ('completed', 'failed') AND acknowledged_at IS NULL
            ORDER BY received_at, right_id, release_id
            """
        ).fetchall()
        return [self._task(row) for row in rows]

    def mark_processed(
        self,
        task: AssetRevocationTask,
        *,
        status: str,
        cache_cleared: bool,
        fallback_applied: bool,
        message: str,
    ) -> AssetRevocationTask:
        if status not in {"completed", "failed"}:
            raise ValueError("撤销任务状态无效")
        now = datetime.now(UTC).isoformat()
        with self.local_store.transaction() as connection:
            connection.execute(
                """
                UPDATE asset_revocation_tasks
                SET status=?, cache_cleared=?, fallback_applied=?, message=?,
                    process_attempts=process_attempts+1, processed_at=?
                WHERE right_id=? AND release_id=?
                """,
                (
                    status,
                    int(cache_cleared),
                    int(fallback_applied),
                    message[:1000],
                    now,
                    task.right_id,
                    task.release_id,
                ),
            )
        return self.get(task.right_id, task.release_id)

    def mark_acknowledged(self, right_id: str, release_id: str) -> None:
        with self.local_store.transaction() as connection:
            connection.execute(
                """
                UPDATE asset_revocation_tasks SET acknowledged_at=?
                WHERE right_id=? AND release_id=?
                """,
                (datetime.now(UTC).isoformat(), right_id, release_id),
            )

    def get(self, right_id: str, release_id: str) -> AssetRevocationTask:
        row = self.local_store._connection.execute(
            """
            SELECT * FROM asset_revocation_tasks
            WHERE right_id=? AND release_id=?
            """,
            (right_id, release_id),
        ).fetchone()
        if row is None:
            raise KeyError((right_id, release_id))
        return self._task(row)

    @staticmethod
    def _task(row) -> AssetRevocationTask:
        return AssetRevocationTask(
            right_id=str(row["right_id"]),
            artifact_id=str(row["artifact_id"]),
            pet_id=str(row["pet_id"]),
            release_id=str(row["release_id"]),
            template_id=str(row["template_id"]),
            identity_version=str(row["identity_version"]),
            asset_version=str(row["asset_version"]),
            reason=str(row["reason"]),
            status=str(row["status"]),
            cache_cleared=bool(row["cache_cleared"]),
            fallback_applied=bool(row["fallback_applied"]),
            message=str(row["message"]),
            processed_at=(
                datetime.fromisoformat(str(row["processed_at"]))
                if row["processed_at"]
                else None
            ),
            acknowledged_at=(
                datetime.fromisoformat(str(row["acknowledged_at"]))
                if row["acknowledged_at"]
                else None
            ),
        )


def _marker_path(cache_root: Path, identity: PetAssetIdentity) -> Path:
    digest = hashlib.sha256("\0".join(identity.key).encode("utf-8")).hexdigest()
    return cache_root / ".revoked" / f"{digest}.json"


def is_identity_revoked(cache_root: Path, identity: PetAssetIdentity) -> bool:
    return _marker_path(Path(cache_root), identity).is_file()


def mark_identity_revoked(
    cache_root: Path,
    identity: PetAssetIdentity,
    *,
    right_id: str,
    release_id: str,
    reason: str,
) -> None:
    marker = _marker_path(Path(cache_root), identity)
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            {
                "right_id": right_id,
                "release_id": release_id,
                "template_id": identity.template_id,
                "identity_version": identity.identity_version,
                "asset_version": identity.asset_version,
                "reason": reason,
                "revoked_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    temporary.replace(marker)


def evict_identity_cache(cache_root: Path, identity: PetAssetIdentity) -> bool:
    root = Path(cache_root).resolve()
    destination = (
        root
        / _slug(identity.template_id)
        / _slug(identity.identity_version)
        / _slug(identity.asset_version)
    ).resolve()
    if root not in destination.parents:
        raise ValueError("撤销素材缓存路径逃逸")
    existed = destination.exists()
    shutil.rmtree(destination, ignore_errors=False)
    shutil.rmtree(destination.with_name(destination.name + ".installing"), ignore_errors=True)
    shutil.rmtree(destination.with_name(destination.name + ".previous"), ignore_errors=True)
    return existed


def process_asset_revocations(
    task_store: AssetRevocationTaskStore,
    cache_roots: list[Path],
) -> list[AssetRevocationTask]:
    processed: list[AssetRevocationTask] = []
    unique_roots = list(dict.fromkeys(Path(path) for path in cache_roots))
    for task in task_store.list_processable():
        try:
            for root in unique_roots:
                mark_identity_revoked(
                    root,
                    task.identity,
                    right_id=task.right_id,
                    release_id=task.release_id,
                    reason=task.reason,
                )
                evict_identity_cache(root, task.identity)
            processed.append(
                task_store.mark_processed(
                    task,
                    status="completed",
                    cache_cleared=True,
                    fallback_applied=True,
                    message="撤销素材缓存已清理，安全兼容形象策略已启用。",
                )
            )
        except (OSError, RuntimeError, ValueError) as exc:
            processed.append(
                task_store.mark_processed(
                    task,
                    status="failed",
                    cache_cleared=False,
                    fallback_applied=False,
                    message=str(exc),
                )
            )
    return processed


_KNOWN_CACHE_ROOTS: set[Path] = {user_data_dir() / "pet-assets"}
_RUNTIME_INSTALLED = False


def install_asset_revocation_runtime(asset_download_module, catalog_cls) -> None:
    """Install revocation guards before cloud and desktop objects are instantiated."""

    global _RUNTIME_INSTALLED
    if _RUNTIME_INSTALLED:
        return
    _RUNTIME_INSTALLED = True

    original_catalog_selection = catalog_cls.selection_for
    original_catalog_install = catalog_cls.install_package

    def guarded_selection(self, profile):
        identity = PetAssetIdentity(
            profile.identity.template_id,
            profile.identity.identity_version,
            profile.asset_version,
        )
        if is_identity_revoked(self.cache_root, identity):
            demo = getattr(self, "_demo", None)
            if demo is None:
                raise FileNotFoundError("撤销素材已禁用，但没有可用的安全兼容形象")
            return PetAssetSelection(demo.path, demo.identity, "fallback-revoked", False)
        return original_catalog_selection(self, profile)

    def guarded_catalog_install(self, source_manifest_path, *, expected=None):
        from .pet_assets import load_pet_asset_manifest

        source = load_pet_asset_manifest(source_manifest_path)
        if is_identity_revoked(self.cache_root, source.identity):
            raise ValueError("该宠物形象版本已被撤销，禁止重新安装")
        return original_catalog_install(self, source_manifest_path, expected=expected)

    catalog_cls.selection_for = guarded_selection
    catalog_cls.install_package = guarded_catalog_install

    original_download_init = asset_download_module.AssetPackageDownloadController.__init__
    original_public_request = asset_download_module.AssetPackageDownloadController.request_for
    original_private_request = asset_download_module.AssetPackageDownloadController.request_private_release_for
    original_install_zip = asset_download_module.install_asset_package_zip

    def download_init(self, *args, **kwargs):
        original_download_init(self, *args, **kwargs)
        _KNOWN_CACHE_ROOTS.add(Path(self.catalog.cache_root))

    def guarded_request(self, profile):
        identity = PetAssetIdentity(
            profile.identity.template_id,
            profile.identity.identity_version,
            profile.asset_version,
        )
        if is_identity_revoked(self.catalog.cache_root, identity):
            self.status_message.emit("该专属形象已撤销，继续使用安全兼容形象")
            return False
        return original_public_request(self, profile)

    def guarded_private_request(self, profile, access_token):
        identity = PetAssetIdentity(
            profile.identity.template_id,
            profile.identity.identity_version,
            profile.asset_version,
        )
        if is_identity_revoked(self.catalog.cache_root, identity):
            self.status_message.emit("该专属形象已撤销，禁止重新下载")
            return False
        return original_private_request(self, profile, access_token)

    def guarded_install_zip(data, metadata, catalog, **kwargs):
        if is_identity_revoked(catalog.cache_root, metadata.identity):
            raise ValueError("下载中的宠物形象已被撤销，安装已取消")
        return original_install_zip(data, metadata, catalog, **kwargs)

    asset_download_module.AssetPackageDownloadController.__init__ = download_init
    asset_download_module.AssetPackageDownloadController.request_for = guarded_request
    asset_download_module.AssetPackageDownloadController.request_private_release_for = guarded_private_request
    asset_download_module.install_asset_package_zip = guarded_install_zip

    from .cloud_api import CloudApiClient
    from .cloud_session import CloudConnectionState, CloudSessionController

    def acknowledge_asset_revocation(self, task: AssetRevocationTask) -> None:
        if task.processed_at is None:
            raise ValueError("撤销任务尚未处理")
        operation = f"asset_revocation_ack:{task.right_id}:{task.release_id}"
        self._json_request(
            operation,
            "POST",
            f"/api/v1/asset-revocations/{task.right_id}/acknowledgements",
            {
                "artifact_id": task.artifact_id,
                "release_id": task.release_id,
                "pet_id": task.pet_id,
                "status": task.status,
                "cache_cleared": task.cache_cleared,
                "fallback_applied": task.fallback_applied,
                "message": task.message,
                "processed_at": task.processed_at.isoformat(),
            },
            token=self._require_device_token(),
        )

    CloudApiClient.acknowledge_asset_revocation = acknowledge_asset_revocation

    original_session_init = CloudSessionController.__init__
    original_session_start = CloudSessionController.start
    original_session_sync = CloudSessionController.sync_now
    original_session_success = CloudSessionController._on_success
    original_session_failure = CloudSessionController._on_failure

    def session_init(self, *args, **kwargs):
        original_session_init(self, *args, **kwargs)
        self.asset_revocation_tasks = AssetRevocationTaskStore(self.store)
        self._pending_asset_revocation_acks = set()

    def send_pending_acknowledgements(self) -> None:
        if self.identity is None or self.state not in {
            CloudConnectionState.CONNECTED,
            CloudConnectionState.SYNCING,
        }:
            return
        for task in self.asset_revocation_tasks.list_unacknowledged():
            if task.key in self._pending_asset_revocation_acks:
                continue
            self._pending_asset_revocation_acks.add(task.key)
            try:
                self.api.acknowledge_asset_revocation(task)
            except (RuntimeError, ValueError) as exc:
                self._pending_asset_revocation_acks.discard(task.key)
                self.status_message.emit(f"撤销清理回执等待重试：{exc}")

    def process_pending_revocations(self) -> None:
        processed = process_asset_revocations(
            self.asset_revocation_tasks,
            list(_KNOWN_CACHE_ROOTS),
        )
        if processed:
            completed = sum(item.status == "completed" for item in processed)
            failed = len(processed) - completed
            self.pets_changed.emit()
            if failed:
                self.status_message.emit(
                    f"已安全处理 {completed} 个撤销素材，{failed} 个缓存清理任务等待重试"
                )
            else:
                self.status_message.emit(
                    f"已清理 {completed} 个撤销素材并切换安全兼容形象"
                )
        send_pending_acknowledgements(self)

    def session_start(self):
        process_pending_revocations(self)
        return original_session_start(self)

    def session_sync(self):
        process_pending_revocations(self)
        return original_session_sync(self)

    def session_success(self, operation, payload):
        if operation.startswith("asset_revocation_ack:"):
            parts = operation.split(":", 2)
            if len(parts) == 3:
                key = (parts[1], parts[2])
                self.asset_revocation_tasks.mark_acknowledged(*key)
                self._pending_asset_revocation_acks.discard(key)
                self.status_message.emit("撤销素材缓存清理回执已同步")
            return
        if operation == "events" and isinstance(payload, dict):
            self.asset_revocation_tasks.queue_from_sync_payload(payload)
        original_session_success(self, operation, payload)
        if operation in {"bootstrap", "events", "device_token"}:
            process_pending_revocations(self)

    def session_failure(self, operation, status, detail):
        if operation.startswith("asset_revocation_ack:"):
            parts = operation.split(":", 2)
            if len(parts) == 3:
                self._pending_asset_revocation_acks.discard((parts[1], parts[2]))
            if status == 401 and getattr(self, "_credentials", None) is not None:
                if not getattr(self, "_refresh_attempted", False):
                    self._refresh_attempted = True
                    self.api.set_device_token(None)
                    self._exchange_device_token()
                    return
            self.status_message.emit(f"撤销清理回执等待网络恢复后重试：{detail}")
            return
        original_session_failure(self, operation, status, detail)

    CloudSessionController.__init__ = session_init
    CloudSessionController.start = session_start
    CloudSessionController.sync_now = session_sync
    CloudSessionController._on_success = session_success
    CloudSessionController._on_failure = session_failure
