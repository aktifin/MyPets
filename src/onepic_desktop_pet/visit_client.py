"""Desktop transport controller for asynchronous friend pet visits."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController
from .social_client import SocialTransport


class VisitController(QObject):
    snapshot_changed = Signal(object)
    status_message = Signal(str)
    operation_failed = Signal(str)
    pets_sync_requested = Signal()

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
        self.active_pet_id: str | None = None
        self.selected_friend_account_id: str | None = None
        self.snapshot: dict[str, object] = {}
        self._pending_refresh: set[str] = set()
        self.transport.operation_succeeded.connect(self._on_success)
        self.transport.operation_failed.connect(self._on_failure)
        self.session.state_changed.connect(self._session_changed)

    def refresh(self, active_pet_id: str | None) -> bool:
        self.active_pet_id = active_pet_id
        if not self.session.connected:
            self.operation_failed.emit("云端未连接，无法读取串门数据")
            return False
        requests = {
            "friends": ("GET", "/api/v1/friends"),
            "visits": ("GET", "/api/v1/visits"),
        }
        self._pending_refresh = set(requests)
        try:
            for operation, (method, path) in requests.items():
                self.transport.request(operation, method, path)
        except (RuntimeError, ValueError) as exc:
            self._pending_refresh.clear()
            self.operation_failed.emit(str(exc))
            return False
        self.status_message.emit("正在刷新串门数据…")
        return True

    def load_friend_pets(self, friend_account_id: str) -> None:
        if not self.session.connected:
            self.operation_failed.emit("云端未连接，无法读取好友宠物")
            return
        value = friend_account_id.strip()
        if not value:
            self.operation_failed.emit("请选择好友")
            return
        self.selected_friend_account_id = value
        try:
            self.transport.request(
                "friend_pets",
                "GET",
                f"/api/v1/friends/{value}/pets",
            )
        except (RuntimeError, ValueError) as exc:
            self.operation_failed.emit(str(exc))
            return
        self.status_message.emit("正在读取好友可接待的宠物…")

    def request_visit(
        self,
        host_username: str,
        host_pet_id: str,
        duration_minutes: int,
        note: str,
    ) -> None:
        if not self.active_pet_id:
            self.operation_failed.emit("当前宠物不是可发起串门的自有宠物")
            return
        self._mutate(
            "request_visit",
            "POST",
            "/api/v1/visits",
            {
                "host_username": host_username.strip(),
                "visitor_pet_id": self.active_pet_id,
                "host_pet_id": host_pet_id.strip(),
                "duration_minutes": int(duration_minutes),
                "note": note.strip(),
            },
        )

    def respond_visit(self, visit_id: str, action: str) -> None:
        if action not in {"accept", "reject", "cancel"}:
            raise ValueError("不支持的串门申请操作")
        self._mutate(
            f"visit_{action}",
            "POST",
            f"/api/v1/visits/{visit_id}/{action}",
        )

    def recall_visit(self, visit_id: str) -> None:
        self._mutate(
            "visit_recall",
            "POST",
            f"/api/v1/visits/{visit_id}/recall",
        )

    def _mutate(
        self,
        operation: str,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
    ) -> None:
        if not self.session.connected:
            self.operation_failed.emit("云端未连接，串门操作未提交")
            return
        try:
            self.transport.request(f"mutation:{operation}", method, path, body=body)
        except (RuntimeError, ValueError) as exc:
            self.operation_failed.emit(str(exc))

    def _on_success(self, operation: str, payload: object) -> None:
        if operation in self._pending_refresh:
            self.snapshot[operation] = payload
            self._pending_refresh.discard(operation)
            if not self._pending_refresh:
                self.snapshot_changed.emit(dict(self.snapshot))
                self.status_message.emit("串门数据已刷新")
            return
        if operation == "friend_pets":
            self.snapshot[operation] = payload
            self.snapshot_changed.emit(dict(self.snapshot))
            self.status_message.emit("好友宠物已加载")
            return
        if not operation.startswith("mutation:"):
            return
        label = operation.removeprefix("mutation:")
        self.status_message.emit(
            {
                "request_visit": "串门申请已发送",
                "visit_accept": "串门申请已接受",
                "visit_reject": "串门申请已拒绝",
                "visit_cancel": "串门申请已取消",
                "visit_recall": "宠物已召回",
            }.get(label, "串门操作已完成")
        )
        if label in {"visit_accept", "visit_recall"}:
            self.pets_sync_requested.emit()
        self.refresh(self.active_pet_id)

    def _on_failure(self, operation: str, _status: int, detail: str) -> None:
        self._pending_refresh.discard(operation)
        self.operation_failed.emit(detail)

    def _session_changed(self, state: str) -> None:
        if state == "connected":
            self.refresh(self.active_pet_id)
        elif state in {"offline", "disabled", "error"}:
            self._pending_refresh.clear()
