"""Read-only desktop client for visit timelines and related customer detail targets."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController
from .social_client import SocialTransport


class CustomerNavigationClient(QObject):
    """Load projected customer views without creating another desktop state store."""

    timeline_received = Signal(object)
    target_received = Signal(str, object)
    request_failed = Signal(str, str)

    def __init__(
        self,
        session: CloudSessionController,
        api: CloudApiClient,
        *,
        transport: SocialTransport | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.transport = transport or SocialTransport(api, parent=self)
        self._pending: set[str] = set()
        self.transport.operation_succeeded.connect(self._on_success)
        self.transport.operation_failed.connect(self._on_failure)
        self.session.state_changed.connect(self._session_changed)

    def load_timeline(self, visit_id: str) -> bool:
        value = visit_id.strip()
        if not value:
            self.request_failed.emit("timeline", "串门标识不能为空")
            return False
        return self._request(
            f"timeline:{value}",
            f"/api/v1/visits/{value}/timeline",
        )

    def load_conversation_target(self, conversation_id: str) -> bool:
        value = conversation_id.strip()
        if not value:
            self.request_failed.emit("target", "会话标识不能为空")
            return False
        return self._request(
            f"target:{value}",
            f"/api/v1/conversations/{value}/target",
        )

    def _request(self, operation: str, path: str) -> bool:
        if not self.session.connected:
            self.request_failed.emit(operation.split(":", 1)[0], "云端未连接")
            return False
        if operation in self._pending:
            return False
        self._pending.add(operation)
        try:
            self.transport.request(operation, "GET", path)
        except (RuntimeError, ValueError) as exc:
            self._pending.discard(operation)
            self.request_failed.emit(operation.split(":", 1)[0], str(exc))
            return False
        return True

    def _on_success(self, operation: str, payload: object) -> None:
        self._pending.discard(operation)
        if operation.startswith("timeline:"):
            if isinstance(payload, dict):
                self.timeline_received.emit(dict(payload))
            else:
                self.request_failed.emit("timeline", "串门时间线响应无效")
            return
        if operation.startswith("target:"):
            conversation_id = operation.split(":", 1)[1]
            if isinstance(payload, dict):
                self.target_received.emit(conversation_id, dict(payload))
            else:
                self.request_failed.emit("target", "关联详情响应无效")

    def _on_failure(self, operation: str, _status: int, detail: str) -> None:
        self._pending.discard(operation)
        self.request_failed.emit(operation.split(":", 1)[0], detail)

    def _session_changed(self, state: str) -> None:
        if state in {"offline", "disabled", "error"}:
            self._pending.clear()
