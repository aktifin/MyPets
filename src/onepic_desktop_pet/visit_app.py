"""Asynchronous visits, realtime refresh, and desktop dual-pet scene orchestration."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction

from .domain import PetIdentity, PetProfile, PresenceStatus
from .pet_registry import LOCAL_ACCOUNT_ID
from .presentation.away_indicator import AwayIndicator
from .presentation.dual_pet_scene import DualPetSceneCoordinator
from .presentation.guest_pet_window import GuestPetWindow
from .realtime import RealtimeClient
from .social_app import SocialDesktopPetApplication
from .visit_client import VisitController
from .visit_dialog import VisitDialog


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _nested_id(value: dict[str, object], field: str) -> str:
    nested = _mapping(value.get(field))
    key = "account_id" if field in {"requester", "host"} else "pet_id"
    return str(nested.get(key) or "").strip()


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def guest_profile_from_scene(scene: object) -> PetProfile | None:
    """Build only the public asset identity needed to render the visiting pet."""

    value = _mapping(scene)
    pet = _mapping(value.get("visitor_pet"))
    requester = _mapping(value.get("requester"))
    required = {
        "pet_id": str(pet.get("pet_id") or "").strip(),
        "name": str(pet.get("name") or "").strip(),
        "template_id": str(pet.get("template_id") or "").strip(),
        "template_version": str(pet.get("template_version") or "").strip(),
        "identity_version": str(pet.get("identity_version") or "").strip(),
        "asset_version": str(pet.get("asset_version") or "").strip(),
        "owner_id": str(requester.get("account_id") or "").strip(),
    }
    if any(not item for item in required.values()):
        return None
    presence_value = str(pet.get("presence") or "home").strip().lower()
    try:
        presence = PresenceStatus(presence_value)
    except ValueError:
        presence = PresenceStatus.VISITING
    return PetProfile(
        identity=PetIdentity(
            pet_id=required["pet_id"],
            name=required["name"],
            template_id=required["template_id"],
            template_version=required["template_version"],
            identity_version=required["identity_version"],
            primary_owner_account_id=required["owner_id"],
        ),
        presence=presence,
        personality_type=str(pet.get("personality_type") or "balanced"),
        asset_version=required["asset_version"],
        updated_at=datetime.now().astimezone(),
    )


class VisitDesktopPetApplication(SocialDesktopPetApplication):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.visit_controller = VisitController(
            self.cloud_session,
            self.cloud_api,
            parent=self.qt_app,
        )
        self.realtime_client = RealtimeClient(self.cloud_api, parent=self.qt_app)
        self.scene_coordinator = DualPetSceneCoordinator()
        self._visit_dialog: VisitDialog | None = None
        self._guest_window: GuestPetWindow | None = None
        self._away_indicator: AwayIndicator | None = None
        self._guest_profile: PetProfile | None = None
        self._active_scene: dict[str, object] | None = None
        self._known_pending_visit_ids: set[str] = set()
        self._realtime_refresh_pending = False
        self._away_mode_active = False
        self._main_window_was_visible = False
        self._main_window_was_paused = False

        self._scene_timer = QTimer(self.qt_app)
        self._scene_timer.setInterval(500)
        self._scene_timer.timeout.connect(self._maintain_scene_positions)

        self.visit_action = QAction("异步串门…", self.tray_menu)
        self.visit_action.triggered.connect(self.open_visit_dialog)
        self.tray_menu.insertAction(self.social_action, self.visit_action)

        self.visit_controller.snapshot_changed.connect(self._visit_snapshot_changed)
        self.visit_controller.scene_changed.connect(self._visit_scene_changed)
        self.visit_controller.interaction_succeeded.connect(
            self._visit_interaction_succeeded
        )
        self.visit_controller.status_message.connect(self._visit_status)
        self.visit_controller.operation_failed.connect(self._visit_failed)
        self.visit_controller.pets_sync_requested.connect(self.cloud_session.sync_now)
        self.cloud_session.state_changed.connect(self._cloud_state_for_visits_and_realtime)
        self.realtime_client.cursor_available.connect(self._realtime_cursor_available)
        self.realtime_client.status_message.connect(self._realtime_status)
        self.asset_downloader.package_installed.connect(self._guest_asset_installed)

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
        self._visit_dialog.set_context(
            account_id=identity.account_id if identity else None,
            display_name=identity.display_name if identity else "",
            active_pet_id=active_pet_id,
            active_pet_name=self.active_pet.identity.name if active_is_cloud else "",
            can_request=self._visit_active_pet_id() is not None,
        )
        self.visit_controller.active_pet_id = self._visit_active_pet_id()

    def _visit_snapshot_changed(self, snapshot: object) -> None:
        if self._visit_dialog is not None:
            self._visit_dialog.apply_snapshot(snapshot)
        value = _mapping(snapshot)
        visits = _mapping(value.get("visits"))
        if not visits:
            self._update_guest_window(None)
            self._update_away_indicator(None)
            return

        incoming = visits.get("incoming_requests", [])
        current_ids = {
            str(item.get("visit_id"))
            for item in incoming
            if isinstance(item, dict) and item.get("visit_id")
        } if isinstance(incoming, list) else set()
        new_ids = current_ids - self._known_pending_visit_ids
        self._known_pending_visit_ids = current_ids
        if new_ids:
            self.tray.showMessage(
                "MyPets 串门",
                f"收到 {len(new_ids)} 个新的串门申请，可在托盘菜单中处理。",
            )

        identity = self.cloud_session.identity
        my_account_id = identity.account_id if identity else ""
        active_pet_id = self.active_pet.identity.pet_id
        guest_visit: dict[str, object] | None = None
        away_visit: dict[str, object] | None = None
        active = visits.get("active", [])
        for raw in active if isinstance(active, list) else []:
            visit = _mapping(raw)
            if (
                _nested_id(visit, "host") == my_account_id
                and _nested_id(visit, "host_pet") == active_pet_id
            ):
                guest_visit = visit
            if _nested_id(visit, "visitor_pet") == active_pet_id:
                away_visit = visit

        self._update_guest_window(guest_visit)
        self._update_away_indicator(away_visit)
        if self._guest_window is not None or self._away_indicator is not None:
            self._scene_timer.start()
        else:
            self._scene_timer.stop()

    def _update_guest_window(self, visit: dict[str, object] | None) -> None:
        if visit is None:
            if self._guest_window is not None:
                self._guest_window.close()
            self._guest_window = None
            self._guest_profile = None
            self._active_scene = None
            return

        visit_id = str(visit.get("visit_id") or "").strip()
        visitor_pet = _mapping(visit.get("visitor_pet"))
        requester = _mapping(visit.get("requester"))
        if not visit_id or not visitor_pet:
            return
        if self._guest_window is None or self._guest_window.visit_id != visit_id:
            if self._guest_window is not None:
                self._guest_window.close()
            window = GuestPetWindow(
                visit_id=visit_id,
                visitor_pet_id=str(visitor_pet.get("pet_id") or ""),
                visitor_pet_name=str(visitor_pet.get("name") or "来访宠物"),
                visitor_owner_name=str(requester.get("display_name") or "好友"),
            )
            window.set_interactions_enabled(False)
            window.send_guest_home_requested.connect(self.visit_controller.send_guest_home)
            window.interaction_requested.connect(self.visit_controller.interact_guest)
            window.show()
            self._guest_window = window
        self.scene_coordinator.place_guest(self.window, self._guest_window)
        self.visit_controller.load_scene(visit_id)

    def _visit_scene_changed(self, scene: object) -> None:
        value = _mapping(scene)
        visit_id = str(value.get("visit_id") or "")
        if self._guest_window is None or self._guest_window.visit_id != visit_id:
            return
        self._active_scene = value
        host_pet = _mapping(value.get("host_pet"))
        can_interact = bool(value.get("can_interact")) and str(
            host_pet.get("pet_id") or ""
        ) == self.active_pet.identity.pet_id
        self._guest_window.set_interactions_enabled(can_interact)

        profile = guest_profile_from_scene(value)
        if profile is None:
            return
        self._guest_profile = profile
        selection = self.asset_catalog.selection_for(profile)
        self._guest_window.set_asset_manifest(selection.manifest_path)
        if not selection.exact:
            self.asset_downloader.set_base_url(self.settings.cloud_base_url)
            self.asset_downloader.request_for(profile)

    def _guest_asset_installed(
        self,
        template_id: str,
        identity_version: str,
        asset_version: str,
        manifest_path: str,
    ) -> None:
        profile = self._guest_profile
        if profile is None or self._guest_window is None:
            return
        if (
            profile.identity.template_id == template_id
            and profile.identity.identity_version == identity_version
            and profile.asset_version == asset_version
        ):
            self._guest_window.set_asset_manifest(manifest_path)

    def _visit_interaction_succeeded(self, visit_id: str, action: str) -> None:
        if self._guest_window is None or self._guest_window.visit_id != visit_id:
            return
        close = action in {"play", "sit_together"}
        self.scene_coordinator.place_guest(
            self.window,
            self._guest_window,
            close_interaction=close,
        )
        self._guest_window.show_interaction(action)
        self.window.show_visit_interaction(action)
        QTimer.singleShot(2400, lambda visit_id=visit_id: self._restore_guest_station(visit_id))

    def _restore_guest_station(self, visit_id: str) -> None:
        if self._guest_window is not None and self._guest_window.visit_id == visit_id:
            self.scene_coordinator.place_guest(self.window, self._guest_window)

    def _update_away_indicator(self, visit: dict[str, object] | None) -> None:
        if visit is None:
            if self._away_indicator is not None:
                self._away_indicator.close()
                self._away_indicator = None
            if self._away_mode_active:
                if self._main_window_was_visible:
                    self.window.show()
                else:
                    self.window.hide()
                self.window.set_paused(self._main_window_was_paused)
                self._away_mode_active = False
                self._main_window_was_visible = False
            return

        visit_id = str(visit.get("visit_id") or "")
        if not visit_id:
            return
        if self._away_indicator is None or self._away_indicator.visit_id != visit_id:
            if self._away_indicator is not None:
                self._away_indicator.close()
            host = _mapping(visit.get("host"))
            visitor_pet = _mapping(visit.get("visitor_pet"))
            indicator = AwayIndicator(
                visit_id=visit_id,
                pet_name=str(visitor_pet.get("name") or self.active_pet.identity.name),
                host_name=str(host.get("display_name") or "好友"),
                note=str(visit.get("note") or ""),
                scheduled_end_at=_parse_datetime(visit.get("scheduled_end_at")),
            )
            indicator.recall_requested.connect(self.visit_controller.recall_visit)
            indicator.show()
            self._away_indicator = indicator
        if not self._away_mode_active:
            self._main_window_was_visible = self.window.isVisible()
            self._main_window_was_paused = self.window.paused
            self._away_mode_active = True
        self.window.set_paused(True)
        self.window.hide()
        self.scene_coordinator.place_indicator(self.window, self._away_indicator)

    def _maintain_scene_positions(self) -> None:
        if self._guest_window is not None and self._guest_window.isVisible():
            self.scene_coordinator.place_guest(self.window, self._guest_window)
        if self._away_indicator is not None and self._away_indicator.isVisible():
            self.scene_coordinator.place_indicator(self.window, self._away_indicator)

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
        self._scene_timer.stop()
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
