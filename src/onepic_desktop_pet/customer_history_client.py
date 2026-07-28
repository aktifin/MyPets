"""Read-only desktop client for account-scoped customer processing history."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController
from .social_client import SocialTransport

_HISTORY_KINDS = {
    "all",
    "friend_request",
    "caregiver_invitation",
    "visit",
    "reminder",
}


class CustomerHistoryClient(QObject):
    history_received = Signal(object)
    request_failed = Signal(str)

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
        self._pending = False
        self.transport.operation_succeeded.connect(self._on_success)
        self.transport.operation_failed.connect(self._on_failure)
        self.session.state_changed.connect(self._on_session_state)

    def refresh(self, *, kind: str = "all", days: int = 30, limit: int = 200) -> bool:
        normalized_kind = kind.strip() or "all"
        if normalized_kind not in _HISTORY_KINDS:
            raise ValueError("不支持的处理记录类型")
        if not self.session.connected:
            self.request_failed.emit("云端未连接，无法读取处理记录")
            return False
        if self._pending:
            return False
        normalized_limit = max(1, min(500, int(limit)))
        normalized_days = max(0, min(3650, int(days)))
        query: dict[str, object] = {
            "kind": normalized_kind,
            "limit": normalized_limit,
        }
        if normalized_days:
            query["days"] = normalized_days
        else:
            query["start"] = "1970-01-01T00:00:00+00:00"
        self._pending = True
        try:
            self.transport.request(
                "customer_history",
                "GET",
                "/api/v1/customer-history",
                query=query,
            )
        except (RuntimeError, ValueError) as exc:
            self._pending = False
            self.request_failed.emit(str(exc))
            return False
        return True

    def _on_success(self, operation: str, payload: object) -> None:
        if operation != "customer_history":
            return
        self._pending = False
        if not isinstance(payload, dict):
            self.request_failed.emit("处理记录响应无效")
            return
        self.history_received.emit(dict(payload))

    def _on_failure(self, operation: str, _status: int, detail: str) -> None:
        if operation != "customer_history":
            return
        self._pending = False
        self.request_failed.emit(detail)

    def _on_session_state(self, state: str) -> None:
        state_value = str(getattr(state, "value", state))
        if state_value in {"offline", "disabled", "error"}:
            self._pending = False
