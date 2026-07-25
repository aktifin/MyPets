"""Asynchronous visit composition root layered on friendship and shared care."""

from __future__ import annotations

from PySide6.QtGui import QAction

from .pet_registry import LOCAL_ACCOUNT_ID
from .presentation.away_indicator import AwayIndicator
from .presentation.guest_pet_window import GuestPetWindow
from .realtime import RealtimeClient
from .social_app import SocialDesktopPetApplication
from .visit_client import VisitController
from .visit_dialog import VisitDialog


class VisitDesktopPetApplication(SocialDesktopPetApplication):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.visit_controller = VisitController(
            self.cloud_session,
            self.cloud_api,
            parent=self.qt_app,
        )
        self.realtime_client = RealtimeClient(self.cloud_api, parent=self.qt_app)
        self._visit_dialog: VisitDialog | None = None
        self._guest_window: GuestPetWindow | None = None
        self._away_indicator: AwayIndicator | None = None
        self._known_pending_visit_ids: set[str] = set()
        self._realtime_refresh_pending = False

        self.visit_action = QAction("异步串门…", self.tray_menu)
        self.visit_action.triggered.connect(self.open_visit_dialog)
        self.tray_menu.insertAction(self.social_action, self.visit_action)

        self.visit_controller.snapshot_changed.connect(self._visit_snapshot_changed)
        self.visit_controller.status_message.connect(self._visit_status)
        self.visit_controller.operation_failed.connect(self._visit_failed)
        self.visit_controller.pets_sync_requested.connect(self.cloud_session.sync_now)
        self.cloud_session.state_changed.connect(self._cloud_state_for_visits_and_realtime)
        self.realtime_client.cursor_available.connect(self._realtime_cursor_available)
        self.realtime_client.status_message.connect(self._realtime_status)

    def open_visit_dialog(self) -> None:
        if self._visit_dialog is None:
            dialog = VisitDialog()
            dialog.refresh_requested.connect(
                lambda: self.visit_controller.refresh(self._visit_active_pet_id())
            )
            dialog.friend_pets_requested.connect(self.visit_controller.load_friend_pets)
            dialog.visit_request_requested.connect(self.visit_controller.request_visit)
            dialog.visit_action_requested.connect(self.visit_controller.respond_visit)
            dialog.visit_recall_requested.connect(self.visit_controller.recall_visit)
            self._visit_dialog = dialog
        self._refresh_visit_context()
        self._visit_dialog.show()
        self._visit_dialog.raise_()
        self._visit_dialog.activateWindow()
        self.visit_controller.refresh(self._visit_active_pet_id())

    def _visit_active_pet_id(self) -> str | None:
        if self.active_pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID:
            return None
        return self._managed_active_pet_id()

    def _refresh_visit_context(self) -> None:
        if self._visit_dialog is None:
            return
        identity = self.cloud_session.identity
        active_is_cloud = self.active_pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID
        active_pet_id = self.active_pet.identity.pet_id if active_is_cloud else None
        can_request = self._visit_active_pet_id() is not None
        self._visit_dialog.set_context(
            account_id=identity.account_id if identity else None,
            display_name=identity.display_name if identity else "",
            active_pet_id=active_pet_id,
            active_pet_name=self.active_pet.identity.name if active_is_cloud else "",
            can_request=can_request,
        )
        self.visit_controller.active_pet_id = self._visit_active_pet_id()

    def _visit_snapshot_changed(self, snapshot: object) -> None:
        if self._visit_dialog is not None:
            self._visit_dialog.apply_snapshot(snapshot)
        if not isinstance(snapshot, dict):
            return
        visits = snapshot.get("visits")
        if not isinstance(visits, dict):
            return

        incoming = visits.get("incoming_requests", [])
        current_ids = {
            str(item.get("visit_id"))
            for item in incoming
            if isinstance(item, dict) and item.get("visit_id")
        }
        new_ids = current_ids - self._known_pending_visit_ids
        self._known_pending_visit_ids = current_ids
        if new_ids:
            self.tray.showMessage(
                "MyPets 串门",
                f"收到 {len(new_ids)} 个新的串门申请，可在托盘菜单中处理。",
            )

        active_visits = visits.get("active", [])
        identity = self.cloud_session.identity
        my_account_id = identity.account_id if identity else None
        my_pet_id = self._visit_active_pet_id()

        guest_visit = None
        away_visit = None
        for v in active_visits:
            if not isinstance(v, dict):
                continue
            if my_account_id and v.get("host_account_id") == my_account_id:
                guest_visit = v
            if my_pet_id and v.get("visitor_pet_id") == my_pet_id:
                away_visit = v

        self._update_guest_window(guest_visit)
        self._update_away_indicator(away_visit)

    def _update_guest_window(self, visit: dict[str, object] | None) -> None:
        if visit is None:
            if self._guest_window is not None:
                self._guest_window.close()
                self._guest_window = None
            return

        visit_id = str(visit.get("visit_id", ""))
        if self._guest_window is not None and self._guest_window.visit_id == visit_id:
            return

        if self._guest_window is not None:
            self._guest_window.close()

        visitor_pet = visit.get("visitor_pet", {})
        host_account = visit.get("host_account", {})
        visitor_pet_id = str(visit.get("visitor_pet_id", ""))
        visitor_pet_name = visitor_pet.get("name", "来访宠物") if isinstance(visitor_pet, dict) else "来访宠物"
        visitor_owner = host_account.get("display_name", "好友") if isinstance(host_account, dict) else "好友"

        window = GuestPetWindow(
            visit_id=visit_id,
            visitor_pet_id=visitor_pet_id,
            visitor_pet_name=visitor_pet_name,
            visitor_owner_name=visitor_owner,
        )
        window.send_guest_home_requested.connect(self.visit_controller.send_guest_home)
        window.show()
        self._guest_window = window

    def _update_away_indicator(self, visit: dict[str, object] | None) -> None:
        if visit is None:
            if self._away_indicator is not None:
                self._away_indicator.close()
                self._away_indicator = None
            self.window.show()
            return

        visit_id = str(visit.get("visit_id", ""))
        if self._away_indicator is not None and self._away_indicator.visit_id == visit_id:
            return

        if self._away_indicator is not None:
            self._away_indicator.close()

        host_account = visit.get("host_account", {})
        host_name = host_account.get("display_name", "好友") if isinstance(host_account, dict) else "好友"
        note = str(visit.get("note", ""))

        indicator = AwayIndicator(
            visit_id=visit_id,
            pet_name=self.active_pet.identity.name,
            host_name=host_name,
            note=note,
        )
        indicator.recall_requested.connect(self.visit_controller.recall_visit)
        indicator.show()
        self._away_indicator = indicator

    def _cloud_state_for_visits_and_realtime(self, state: str) -> None:
        self._refresh_visit_context()
        if state == "connected":
            self.realtime_client.start()
            if self._realtime_refresh_pending:
                self._realtime_refresh_pending = False
                self.reminder_cloud.refresh()
                self.social_controller.refresh(self._managed_active_pet_id())
                self.visit_controller.refresh(self._visit_active_pet_id())
        elif state in {"disabled", "offline"}:
            self.realtime_client.stop()

    def _realtime_cursor_available(self, _cursor: int) -> None:
        self._realtime_refresh_pending = True
        self.cloud_session.sync_now()

    def _realtime_status(self, message: str) -> None:
        if "不可用" in message or "异常" in message:
            self.tray.setToolTip(f"{self.active_pet.identity.name} · {message}")

    def _visit_status(self, message: str) -> None:
        if self._visit_dialog is not None:
            self._visit_dialog.set_status(message)
        self.tray.setToolTip(f"{self.active_pet.identity.name} · {message}")

    def _visit_failed(self, message: str) -> None:
        if self._visit_dialog is not None:
            self._visit_dialog.set_status(message, error=True)
        self.tray.setToolTip(f"{self.active_pet.identity.name} · 串门操作失败：{message}")

    def _pets_changed(self) -> None:
        super()._pets_changed()
        self._refresh_visit_context()
        if self.cloud_session.connected:
            self.visit_controller.refresh(self._visit_active_pet_id())

    def quit(self) -> None:
        if self._quitting:
            return
        self.realtime_client.stop()
        if self._guest_window is not None:
            self._guest_window.close()
        if self._away_indicator is not None:
            self._away_indicator.close()
        if self._visit_dialog is not None:
            self._visit_dialog.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return VisitDesktopPetApplication().start(smoke_test_ms=smoke_test_ms)
