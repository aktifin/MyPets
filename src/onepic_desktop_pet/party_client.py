"""Desktop multi-pet party client using the existing authenticated cloud session.

This client owns no synchronization cursor, local database, reminder worker, or secondary pet
runtime.  It is a thin request facade for one party dialog.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController
from .social_client import SocialTransport


PARTY_ACTIONS = {
    "greet_circle",
    "play_together",
    "group_photo",
    "rest_together",
}


class PartyClient(QObject):
    snapshot_received = Signal(object)
    detail_received = Signal(str, object)
    mutation_succeeded = Signal(str, object)
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
        self.session.state_changed.connect(self._on_session_state)

    def refresh(self) -> bool:
        return self._request("party_list", "GET", "/api/v1/parties")

    def load_detail(self, party_id: str) -> bool:
        value = party_id.strip()
        if not value:
            self.request_failed.emit("party_detail", "聚会编号不能为空")
            return False
        return self._request(
            f"party_detail:{value}",
            "GET",
            f"/api/v1/parties/{value}",
        )

    def create_party(
        self,
        pet_id: str,
        *,
        title: str = "宠物小聚会",
        duration_minutes: int = 60,
        max_members: int = 4,
    ) -> bool:
        return self._request(
            "party_create",
            "POST",
            "/api/v1/parties",
            body={
                "host_pet_id": pet_id,
                "title": title.strip() or "宠物小聚会",
                "note": "由 Windows 桌面端发起",
                "duration_minutes": max(15, min(180, int(duration_minutes))),
                "max_members": max(2, min(4, int(max_members))),
            },
        )

    def invite(self, party_id: str, username: str) -> bool:
        return self._request(
            f"party_invite:{party_id}",
            "POST",
            f"/api/v1/parties/{party_id}/invitations",
            body={"username": username.strip()},
        )

    def accept(self, party_id: str, pet_id: str) -> bool:
        return self._request(
            f"party_accept:{party_id}",
            "POST",
            f"/api/v1/parties/{party_id}/accept",
            body={"pet_id": pet_id},
        )

    def decline(self, party_id: str) -> bool:
        return self._mutate(party_id, "decline")

    def start(self, party_id: str) -> bool:
        return self._mutate(party_id, "start")

    def cancel(self, party_id: str) -> bool:
        return self._mutate(party_id, "cancel")

    def leave(self, party_id: str) -> bool:
        return self._mutate(party_id, "leave")

    def end(self, party_id: str) -> bool:
        return self._mutate(party_id, "end")

    def interact(self, party_id: str, action: str, idempotency_key: str) -> bool:
        if action not in PARTY_ACTIONS:
            raise ValueError("不支持的聚会互动动作")
        return self._request(
            f"party_interact:{party_id}:{action}",
            "POST",
            f"/api/v1/parties/{party_id}/interactions/{action}",
            body={"idempotency_key": idempotency_key},
        )

    def _mutate(self, party_id: str, action: str) -> bool:
        return self._request(
            f"party_{action}:{party_id}",
            "POST",
            f"/api/v1/parties/{party_id}/{action}",
        )

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
    ) -> bool:
        if not self.session.connected:
            self.request_failed.emit(operation, "云端未连接，无法处理宠物聚会")
            return False
        if operation in self._pending:
            return False
        self._pending.add(operation)
        try:
            self.transport.request(operation, method, path, body=body)
        except (RuntimeError, ValueError) as exc:
            self._pending.discard(operation)
            self.request_failed.emit(operation, str(exc))
            return False
        return True

    def _on_success(self, operation: str, payload: object) -> None:
        self._pending.discard(operation)
        if operation == "party_list":
            if not isinstance(payload, dict):
                self.request_failed.emit(operation, "聚会列表响应无效")
                return
            self.snapshot_received.emit(dict(payload))
            return
        if operation.startswith("party_detail:"):
            party_id = operation.split(":", 1)[1]
            if not isinstance(payload, dict):
                self.request_failed.emit(operation, "聚会详情响应无效")
                return
            self.detail_received.emit(party_id, dict(payload))
            return
        self.mutation_succeeded.emit(operation, payload)

    def _on_failure(self, operation: str, _status: int, detail: str) -> None:
        self._pending.discard(operation)
        self.request_failed.emit(operation, detail)

    def _on_session_state(self, state: str) -> None:
        state_value = str(getattr(state, "value", state))
        if state_value in {"offline", "disabled", "error"}:
            self._pending.clear()
