"""Device-token client for message search, unread navigation, and quick replies."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController
from .social_client import SocialTransport


_CATEGORIES = {"direct", "friend_pet", "visit", "shared_care"}


class MessageEfficiencyClient(QObject):
    search_received = Signal(str, object)
    window_received = Signal(str, object)
    unread_received = Signal(str, object)
    quick_replies_received = Signal(object)
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
        self.transport.operation_succeeded.connect(self._on_success)
        self.transport.operation_failed.connect(self._on_failure)
        self.session.state_changed.connect(self._on_session_state)
        self._pending: set[str] = set()

    def search(self, query: str, *, limit: int = 100) -> bool:
        normalized = " ".join(query.split())
        if not normalized:
            return False
        return self._request(
            f"message_search:{normalized}",
            "GET",
            "/api/v1/message-search",
            query={"query": normalized, "limit": max(1, min(100, int(limit)))},
        )

    def load_window(
        self,
        conversation_id: str,
        *,
        center_sequence: int = 0,
        before: int = 45,
        after: int = 45,
    ) -> bool:
        normalized = conversation_id.strip()
        if not normalized:
            return False
        query: dict[str, object] = {
            "before": max(0, min(100, int(before))),
            "after": max(0, min(100, int(after))),
        }
        if center_sequence > 0:
            query["center_sequence"] = int(center_sequence)
        return self._request(
            f"message_window:{normalized}",
            "GET",
            f"/api/v1/conversations/{normalized}/message-window",
            query=query,
        )

    def load_unread(self, conversation_id: str, *, current_sequence: int = 0) -> bool:
        normalized = conversation_id.strip()
        if not normalized:
            return False
        query = {"current_sequence": int(current_sequence)} if current_sequence > 0 else None
        return self._request(
            f"message_unread:{normalized}",
            "GET",
            f"/api/v1/conversations/{normalized}/unread-navigation",
            query=query,
        )

    def load_quick_replies(self) -> bool:
        return self._request(
            "message_quick_replies",
            "GET",
            "/api/v1/message-quick-replies",
        )

    def update_quick_replies(self, category: str, values: list[str]) -> bool:
        normalized_category = category.strip()
        if normalized_category not in _CATEGORIES:
            raise ValueError("不支持的快捷回复分类")
        normalized_values = [str(item).strip() for item in values if str(item).strip()]
        if not 1 <= len(normalized_values) <= 6:
            raise ValueError("每类快捷回复需要保留 1 至 6 条")
        return self._request(
            f"message_quick_update:{normalized_category}",
            "PATCH",
            "/api/v1/message-quick-replies",
            body={"categories": {normalized_category: normalized_values}},
        )

    def reset_quick_replies(self, category: str = "all") -> bool:
        normalized = category.strip() or "all"
        if normalized != "all" and normalized not in _CATEGORIES:
            raise ValueError("不支持的快捷回复分类")
        return self._request(
            f"message_quick_reset:{normalized}",
            "POST",
            "/api/v1/message-quick-replies/reset",
            body={"category": normalized},
        )

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        query: dict[str, object] | None = None,
    ) -> bool:
        if not self.session.connected:
            self.request_failed.emit(operation, "云端未连接，无法读取消息效率数据")
            return False
        if operation in self._pending:
            return False
        self._pending.add(operation)
        try:
            self.transport.request(operation, method, path, body=body, query=query)
        except (RuntimeError, ValueError) as exc:
            self._pending.discard(operation)
            self.request_failed.emit(operation, str(exc))
            return False
        return True

    def _on_success(self, operation: str, payload: object) -> None:
        self._pending.discard(operation)
        if operation.startswith("message_search:"):
            self.search_received.emit(operation.split(":", 1)[1], payload)
            return
        if operation.startswith("message_window:"):
            self.window_received.emit(operation.split(":", 1)[1], payload)
            return
        if operation.startswith("message_unread:"):
            self.unread_received.emit(operation.split(":", 1)[1], payload)
            return
        if operation == "message_quick_replies" or operation.startswith(
            ("message_quick_update:", "message_quick_reset:")
        ):
            self.quick_replies_received.emit(payload)

    def _on_failure(self, operation: str, _status: int, detail: str) -> None:
        self._pending.discard(operation)
        if operation.startswith("message_"):
            self.request_failed.emit(operation, detail)

    def _on_session_state(self, state: str) -> None:
        state_value = str(getattr(state, "value", state))
        if state_value in {"offline", "disabled", "error"}:
            self._pending.clear()
