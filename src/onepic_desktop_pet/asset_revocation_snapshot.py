"""Bootstrap-time synchronization of currently revoked personal asset releases."""

from __future__ import annotations

from typing import Any

from .asset_revocation import _KNOWN_CACHE_ROOTS, process_asset_revocations
from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController

_INSTALLED = False


def install_asset_revocation_snapshot_runtime() -> None:
    """Patch cloud transport/session after the core revocation runtime is installed."""

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    def fetch_asset_revocations(self) -> None:
        self._request(
            "asset_revocations",
            "GET",
            "/api/v1/asset-revocations",
            token=self._require_device_token(),
        )

    CloudApiClient.fetch_asset_revocations = fetch_asset_revocations

    previous_success = CloudSessionController._on_success
    previous_failure = CloudSessionController._on_failure

    def send_unacknowledged(self) -> None:
        pending = getattr(self, "_pending_asset_revocation_acks", set())
        for task in self.asset_revocation_tasks.list_unacknowledged():
            if task.key in pending:
                continue
            pending.add(task.key)
            try:
                self.api.acknowledge_asset_revocation(task)
            except (RuntimeError, ValueError) as exc:
                pending.discard(task.key)
                self.status_message.emit(f"撤销清理回执等待重试：{exc}")
        self._pending_asset_revocation_acks = pending

    def success(self, operation: str, payload: object) -> None:
        if operation == "asset_revocations":
            if not isinstance(payload, list):
                self.status_message.emit("撤销素材清单响应无效，将在下次同步重试")
                return
            synthetic_events: list[dict[str, Any]] = []
            for item in payload:
                if not isinstance(item, dict):
                    self.status_message.emit("撤销素材清单包含无效项目，将在下次同步重试")
                    return
                right_id = item.get("right_id")
                release_id = item.get("release_id")
                if not isinstance(right_id, str) or not isinstance(release_id, str):
                    self.status_message.emit("撤销素材清单缺少标识，将在下次同步重试")
                    return
                synthetic_events.append(
                    {
                        "event_id": f"revocation-snapshot:{right_id}:{release_id}",
                        "event_type": "asset_revoked",
                        "payload": item,
                    }
                )
            try:
                queued = self.asset_revocation_tasks.queue_from_sync_payload(
                    {"events": synthetic_events}
                )
                processed = process_asset_revocations(
                    self.asset_revocation_tasks,
                    list(_KNOWN_CACHE_ROOTS),
                )
            except (KeyError, OSError, RuntimeError, ValueError) as exc:
                self.status_message.emit(f"撤销素材清单处理失败，将在下次同步重试：{exc}")
                return
            if queued or processed:
                self.pets_changed.emit()
                completed = sum(item.status == "completed" for item in processed)
                failed = len(processed) - completed
                if failed:
                    self.status_message.emit(
                        f"已处理 {completed} 个历史撤销素材，{failed} 个清理任务等待重试"
                    )
                elif completed:
                    self.status_message.emit(
                        f"已同步 {completed} 个历史撤销素材并启用安全兼容形象"
                    )
            send_unacknowledged(self)
            return

        previous_success(self, operation, payload)
        if operation == "bootstrap":
            fetcher = getattr(self.api, "fetch_asset_revocations", None)
            if callable(fetcher):
                try:
                    fetcher()
                except (RuntimeError, ValueError) as exc:
                    self.status_message.emit(f"撤销素材清单等待下次同步：{exc}")

    def failure(self, operation: str, status: int, detail: str) -> None:
        if operation == "asset_revocations":
            self.status_message.emit(f"撤销素材清单等待网络恢复后重试：{detail}")
            return
        previous_failure(self, operation, status, detail)

    CloudSessionController._on_success = success
    CloudSessionController._on_failure = failure
