"""Desktop composition layer for multi-pet status overview and rotation care."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction

from .desktop_experience import build_local_daily_care_summary
from .multi_pet_overview import (
    build_local_overview_item,
    merge_overview_items,
    next_rotation_pet_id,
)
from .multi_pet_overview_client import MultiPetOverviewCloudClient
from .multi_pet_overview_dialog import MultiPetOverviewDialog
from .pending_items_app import PendingItemsApplication
from .pet_registry import LOCAL_ACCOUNT_ID


class MultiPetOverviewApplication(PendingItemsApplication):
    """Add one ordered view across local and cloud pets without bulk auto-care."""

    def __init__(self, *args, **kwargs) -> None:
        self._cloud_multi_pet_items: list[dict[str, object]] = []
        self._multi_pet_dialog: MultiPetOverviewDialog | None = None
        self._queued_rotation_care: tuple[str, str] | None = None
        super().__init__(*args, **kwargs)

        self.multi_pet_action = QAction("多宠状态总览", self.system_tray_menu.menu)
        self.multi_pet_action.triggered.connect(self.open_multi_pet_overview)
        separator = next(
            (
                action
                for action in self.system_tray_menu.menu.actions()
                if action.isSeparator()
            ),
            None,
        )
        if separator is not None:
            self.system_tray_menu.menu.insertAction(separator, self.multi_pet_action)
        else:
            self.system_tray_menu.menu.addAction(self.multi_pet_action)

        self.next_rotation_action = QAction(
            "切换到下一只需要照料",
            self.system_tray_menu.pets_root_menu,
        )
        self.next_rotation_action.triggered.connect(self.switch_next_multi_pet)
        self.system_tray_menu.pets_root_menu.insertAction(
            self.system_tray_menu.create_pet_action,
            self.next_rotation_action,
        )
        self.system_tray_menu.pets_root_menu.insertSeparator(
            self.system_tray_menu.create_pet_action
        )

        self.multi_pet_client = MultiPetOverviewCloudClient(
            self.cloud_api,
            parent=self.qt_app,
        )
        self.multi_pet_client.overview_received.connect(self._multi_pet_received)
        self.multi_pet_client.request_failed.connect(self._multi_pet_failed)
        self.cloud_session.state_changed.connect(self._multi_pet_cloud_state_changed)

        self._multi_pet_timer = QTimer(self.qt_app)
        self._multi_pet_timer.setInterval(2 * 60 * 1000)
        self._multi_pet_timer.timeout.connect(self.refresh_multi_pet_overview)
        self._refresh_multi_pet_actions()
        if self.cloud_session.connected:
            QTimer.singleShot(800, self.refresh_multi_pet_overview)

    @staticmethod
    def _timezone_offset_minutes() -> int:
        offset = datetime.now().astimezone().utcoffset()
        return -round((offset.total_seconds() if offset else 0) / 60)

    def _local_multi_pet_items(self) -> list[dict[str, object]]:
        active_id = self.local_store.get_active_pet_id()
        items: list[dict[str, object]] = []
        for pet in self.pet_registry.list_pets():
            if pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID:
                continue
            records = self.local_store.list_interaction_records(
                pet.identity.pet_id,
                limit=1000,
            )
            daily = build_local_daily_care_summary(records)
            items.append(
                build_local_overview_item(
                    pet,
                    daily,
                    current=pet.identity.pet_id == active_id,
                )
            )
        return items

    def multi_pet_items(self) -> list[dict[str, object]]:
        return merge_overview_items(
            self._local_multi_pet_items(),
            self._cloud_multi_pet_items,
            current_pet_id=self.local_store.get_active_pet_id(),
        )

    def multi_pet_summary(self) -> dict[str, object]:
        items = self.multi_pet_items()
        current_id = self.local_store.get_active_pet_id()
        return {
            "total_count": len(items),
            "needs_attention_count": sum(bool(item.get("needs_attention")) for item in items),
            "urgent_count": sum(item.get("priority") == "urgent" for item in items),
            "care_ready_count": sum(bool(item.get("action_available")) for item in items),
            "next_pet_id": next_rotation_pet_id(items, current_pet_id=current_id),
            "items": items,
        }

    def open_multi_pet_overview(self) -> None:
        if self._multi_pet_dialog is None:
            dialog = MultiPetOverviewDialog()
            dialog.refresh_requested.connect(self.refresh_multi_pet_overview)
            dialog.next_requested.connect(self.switch_next_multi_pet)
            dialog.switch_requested.connect(self._switch_rotation_pet)
            dialog.care_requested.connect(self._care_rotation_pet)
            self._multi_pet_dialog = dialog
        self._sync_multi_pet_dialog()
        self._multi_pet_dialog.show()
        self._multi_pet_dialog.raise_()
        self._multi_pet_dialog.activateWindow()
        self.refresh_multi_pet_overview()

    def refresh_multi_pet_overview(self) -> None:
        self._sync_multi_pet_dialog()
        self._refresh_multi_pet_actions()
        if not self.cloud_session.connected:
            if self._multi_pet_dialog is not None:
                identity = getattr(self.cloud_session, "identity", None)
                self._multi_pet_dialog.set_status(
                    "云端正在同步，先显示本地宠物和上次读取的云端状态。"
                    if identity is not None
                    else "当前显示本地宠物；登录云端后可合并其他宠物。",
                    error=False,
                )
            return
        self.multi_pet_client.refresh(self._timezone_offset_minutes())

    def switch_next_multi_pet(self) -> None:
        next_pet_id = str(self.multi_pet_summary().get("next_pet_id") or "")
        if not next_pet_id:
            if self._multi_pet_dialog is not None:
                self._multi_pet_dialog.set_status("当前没有其他需要查看或可立即照料的宠物。")
            return
        self._switch_rotation_pet(next_pet_id)

    def _switch_rotation_pet(self, pet_id: str) -> bool:
        pet = self.local_store.get_pet(pet_id)
        if pet is None:
            self._queued_rotation_care = None
            if self._multi_pet_dialog is not None:
                self._multi_pet_dialog.set_status("宠物尚未同步到本机，请稍后刷新。", error=True)
            return False
        if (
            pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID
            and not self.cloud_session.connected
        ):
            self._queued_rotation_care = None
            if self._multi_pet_dialog is not None:
                self._multi_pet_dialog.set_status(
                    "云端未连接，暂时不能切换到这只云端宠物。",
                    error=True,
                )
            return False
        self._switch_pet(pet_id)
        if self._multi_pet_dialog is not None:
            self._multi_pet_dialog.set_status(f"正在切换到 {pet.identity.name}…")
        QTimer.singleShot(300, self._sync_multi_pet_after_switch)
        return True

    def _care_rotation_pet(self, pet_id: str, action: str) -> None:
        if pet_id == self.active_pet.identity.pet_id:
            self._request_pet_care(action)
            return
        self._queued_rotation_care = (pet_id, action)
        if not self._switch_rotation_pet(pet_id):
            self._queued_rotation_care = None

    def _sync_multi_pet_after_switch(self) -> None:
        self._sync_multi_pet_dialog()
        self._refresh_multi_pet_actions()

    def _multi_pet_received(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        raw_items = payload.get("items")
        self._cloud_multi_pet_items = (
            [dict(item) for item in raw_items if isinstance(item, dict)]
            if isinstance(raw_items, list)
            else []
        )
        self._sync_multi_pet_dialog()
        self._refresh_multi_pet_actions()

    def _multi_pet_failed(self, message: str) -> None:
        if self._multi_pet_dialog is not None:
            self._multi_pet_dialog.set_status(message, error=True)
        self._refresh_multi_pet_actions()

    def _multi_pet_cloud_state_changed(self, state: str) -> None:
        state_value = str(getattr(state, "value", state))
        if state_value == "connected":
            QTimer.singleShot(500, self.refresh_multi_pet_overview)
        elif state_value == "disabled":
            self._cloud_multi_pet_items = []
            self._queued_rotation_care = None
            self._sync_multi_pet_dialog()
            self._refresh_multi_pet_actions()

    def _sync_multi_pet_dialog(self) -> None:
        if self._multi_pet_dialog is None:
            return
        summary = self.multi_pet_summary()
        self._multi_pet_dialog.set_items(
            summary["items"],
            total_count=int(summary["total_count"]),
            needs_attention_count=int(summary["needs_attention_count"]),
            urgent_count=int(summary["urgent_count"]),
            next_pet_id=str(summary.get("next_pet_id") or "") or None,
        )

    def _refresh_multi_pet_actions(self) -> None:
        summary = self.multi_pet_summary()
        total = int(summary["total_count"])
        needs = int(summary["needs_attention_count"])
        urgent = int(summary["urgent_count"])
        if urgent:
            text = f"多宠状态总览（{needs} 只需关注，{urgent} 只优先）"
        elif needs:
            text = f"多宠状态总览（{needs} 只需关注）"
        else:
            text = "多宠状态总览"
        self.multi_pet_action.setText(text)
        self.multi_pet_action.setEnabled(total >= 2)
        next_pet_id = str(summary.get("next_pet_id") or "")
        self.next_rotation_action.setEnabled(bool(next_pet_id))
        if next_pet_id:
            target = next(
                (
                    item
                    for item in summary["items"]
                    if str(item.get("pet_id") or "") == next_pet_id
                ),
                None,
            )
            self.next_rotation_action.setText(
                f"切换到下一只需关注：{target.get('name')}"
                if isinstance(target, dict)
                else "切换到下一只需要关注"
            )
        else:
            self.next_rotation_action.setText("暂无其他需关注宠物")

    def _pets_changed(self) -> None:
        super()._pets_changed()
        self._sync_multi_pet_dialog()
        self._refresh_multi_pet_actions()
        pending = self._queued_rotation_care
        if pending is not None and self.active_pet.identity.pet_id == pending[0]:
            self._queued_rotation_care = None
            QTimer.singleShot(0, lambda action=pending[1]: self._request_pet_care(action))

    def _pet_care_succeeded(self, action: str, payload: object) -> None:
        super()._pet_care_succeeded(action, payload)
        self._sync_multi_pet_dialog()
        self._refresh_multi_pet_actions()
        QTimer.singleShot(500, self.refresh_multi_pet_overview)

    def _pet_care_failed(self, action: str, message: str) -> None:
        self._queued_rotation_care = None
        super()._pet_care_failed(action, message)
        if self._multi_pet_dialog is not None:
            self._multi_pet_dialog.set_status(message, error=True)
        self._sync_multi_pet_dialog()

    def start(self, smoke_test_ms: int | None = None) -> int:
        if smoke_test_ms is None:
            self._multi_pet_timer.start()
        return super().start(smoke_test_ms=smoke_test_ms)

    def quit(self) -> None:
        if self._quitting:
            return
        self._multi_pet_timer.stop()
        if self._multi_pet_dialog is not None:
            self._multi_pet_dialog.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return MultiPetOverviewApplication().start(smoke_test_ms=smoke_test_ms)
