"""Final customer composition layer for multi-pet summaries and two-pet layout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSystemTrayIcon

from .config import save_settings
from .multi_pet_layout import DualPetLayoutController
from .multi_pet_overview_app import MultiPetOverviewApplication
from .next_pet_prompt import NextPetPrompt
from .pet_registry import LOCAL_ACCOUNT_ID
from .proactive_care import (
    aggregate_local_proactive_notices,
    build_local_proactive_notice,
    is_quiet_time,
)


class MultiPetCareLayoutApplication(MultiPetOverviewApplication):
    """Close the multi-pet care loop without bulk actions or extra app stacks."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._layout_active_pet_id = self.active_pet.identity.pet_id
        self.next_pet_prompt = NextPetPrompt()
        self.next_pet_prompt.switch_requested.connect(self._switch_rotation_pet)
        self.dual_pet_layout = DualPetLayoutController(
            primary_window=self.window,
            settings=self.settings,
            save_callback=lambda: save_settings(self.settings),
            parent=self.qt_app,
        )
        self.dual_pet_layout.companion_activated.connect(self._activate_companion_pet)
        self.dual_pet_layout.companion_hidden.connect(self._refresh_dual_layout_actions)

        pets_menu = self.system_tray_menu.pets_root_menu
        self.dual_pet_action = QAction("双宠并排展示", pets_menu)
        self.dual_pet_action.setCheckable(True)
        self.dual_pet_action.triggered.connect(self.set_dual_pet_layout_enabled)
        self.restore_dual_layout_action = QAction("恢复上次双宠布局", pets_menu)
        self.restore_dual_layout_action.triggered.connect(self.restore_dual_pet_layout)
        self.arrange_dual_layout_action = QAction("重新并排排列", pets_menu)
        self.arrange_dual_layout_action.triggered.connect(self.arrange_dual_pet_layout)
        self.hide_companion_action = QAction("关闭第二只宠物", pets_menu)
        self.hide_companion_action.triggered.connect(
            lambda: self.set_dual_pet_layout_enabled(False)
        )
        pets_menu.insertAction(self.system_tray_menu.create_pet_action, self.dual_pet_action)
        pets_menu.insertAction(
            self.system_tray_menu.create_pet_action, self.restore_dual_layout_action
        )
        pets_menu.insertAction(
            self.system_tray_menu.create_pet_action, self.arrange_dual_layout_action
        )
        pets_menu.insertAction(
            self.system_tray_menu.create_pet_action, self.hide_companion_action
        )
        pets_menu.insertSeparator(self.system_tray_menu.create_pet_action)
        self._refresh_dual_layout_actions()
        if self.settings.multi_pet_layout_enabled:
            QTimer.singleShot(500, self._restore_dual_layout_from_settings)

    # Aggregated proactive care -----------------------------------------

    def _evaluate_local_proactive(self, now: datetime) -> None:
        settings = self.settings
        interval = timedelta(minutes=settings.proactive_min_interval_minutes)
        if settings.proactive_quiet_hours_enabled and is_quiet_time(
            now,
            settings.proactive_quiet_start,
            settings.proactive_quiet_end,
        ):
            self._proactive_next_check_at = datetime.now(UTC) + timedelta(minutes=30)
            return
        today = now.date().isoformat()
        if settings.proactive_notice_date != today:
            settings.proactive_notice_date = today
            settings.proactive_notice_count = 0
        if settings.proactive_notice_count >= settings.proactive_max_daily_notices:
            self._proactive_next_check_at = datetime.now(UTC) + timedelta(hours=2)
            return
        last = self._parse_datetime(settings.proactive_last_notice_at)
        if last is not None and datetime.now(UTC) - last < interval:
            self._proactive_next_check_at = last + interval
            return

        notices: list[dict[str, object]] = []
        for pet in self.pet_registry.list_pets():
            if pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID:
                continue
            records = self.local_store.list_interaction_records(
                pet.identity.pet_id,
                limit=1000,
            )
            notice = build_local_proactive_notice(pet, records, now=now)
            if notice is not None:
                notices.append(notice)
        notice = aggregate_local_proactive_notices(notices)
        if notice is None:
            self._proactive_next_check_at = datetime.now(UTC) + timedelta(minutes=30)
            return

        suppressed_until = self._parse_datetime(settings.proactive_suppressed_until)
        if (
            suppressed_until is not None
            and suppressed_until > datetime.now(UTC)
            and settings.proactive_suppressed_notice_key == notice.get("notice_key")
        ):
            self._proactive_next_check_at = suppressed_until
            return
        settings.proactive_last_notice_at = datetime.now(UTC).isoformat()
        settings.proactive_notice_count += 1
        self._proactive_next_check_at = datetime.now(UTC) + interval
        try:
            save_settings(settings)
        except OSError:
            pass
        self._show_proactive_notice(notice)

    def open_current_proactive_notice(self) -> None:
        notice = self.proactive_notice()
        if notice and (
            str(notice.get("notice_key") or "").startswith("multi-pet:")
            or notice.get("target_section") == "multi_pet"
        ):
            self.open_multi_pet_overview()
            self._acknowledge_current_proactive("opened")
            return
        super().open_current_proactive_notice()

    # Care completion ---------------------------------------------------

    def _present_enhanced_care_success(self, action: str) -> None:
        super()._present_enhanced_care_success(action)
        QTimer.singleShot(350, self._show_next_pet_prompt)

    def _show_next_pet_prompt(self) -> None:
        summary = self.multi_pet_summary()
        next_pet_id = str(summary.get("next_pet_id") or "")
        if not next_pet_id:
            return
        target = next(
            (
                item
                for item in summary.get("items", [])
                if isinstance(item, dict)
                and str(item.get("pet_id") or "") == next_pet_id
            ),
            None,
        )
        if not isinstance(target, dict):
            return
        name = str(target.get("name") or "下一只宠物")
        detail = str(target.get("recommendation_detail") or "还有一只宠物值得看看。")
        self.next_pet_prompt.show_for(
            self.window,
            pet_id=next_pet_id,
            pet_name=name,
            reason=detail,
        )
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage(
                "还有宠物需要关注",
                f"下一只可以看看 {name}。",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )

    # Dual-pet desktop layout ------------------------------------------

    def set_dual_pet_layout_enabled(self, enabled: bool) -> None:
        if not bool(enabled):
            self.dual_pet_layout.hide_companion()
            self.settings.multi_pet_layout_enabled = False
            try:
                save_settings(self.settings)
            except OSError:
                pass
            self._refresh_dual_layout_actions()
            return
        if len(self.multi_pet_items()) < 2:
            self.dual_pet_action.setChecked(False)
            self.tray.showMessage(
                "双宠并排展示",
                "至少需要两只已同步宠物。",
                QSystemTrayIcon.MessageIcon.Information,
                2600,
            )
            return
        self.settings.multi_pet_layout_enabled = True
        self.edge_dock.detach()
        self._sync_dual_pet_layout(use_saved_position=True)
        self._refresh_dual_layout_actions()

    def restore_dual_pet_layout(self) -> None:
        if not self.settings.multi_pet_layout_enabled:
            self.set_dual_pet_layout_enabled(True)
            return
        self._sync_dual_pet_layout(use_saved_position=True)
        self.dual_pet_layout.restore_layout()

    def arrange_dual_pet_layout(self) -> None:
        if not self.settings.multi_pet_layout_enabled:
            self.set_dual_pet_layout_enabled(True)
            return
        self._sync_dual_pet_layout(use_saved_position=False)
        self.dual_pet_layout.arrange_side_by_side()

    def _restore_dual_layout_from_settings(self) -> None:
        if self.settings.multi_pet_layout_enabled:
            self.edge_dock.detach()
            self._sync_dual_pet_layout(use_saved_position=True)

    def _companion_pet_id(self) -> str:
        active_id = self.active_pet.identity.pet_id
        available = {
            str(item.get("pet_id") or "")
            for item in self.multi_pet_items()
            if isinstance(item, dict) and item.get("pet_id")
        }
        preferred = str(self.settings.multi_pet_companion_pet_id or "")
        if preferred and preferred != active_id and preferred in available:
            return preferred
        next_pet = str(self.multi_pet_summary().get("next_pet_id") or "")
        if next_pet and next_pet != active_id:
            return next_pet
        return next((pet_id for pet_id in sorted(available) if pet_id != active_id), "")

    def _sync_dual_pet_layout(self, *, use_saved_position: bool) -> None:
        if not self.settings.multi_pet_layout_enabled:
            return
        companion_id = self._companion_pet_id()
        if not companion_id:
            self.settings.multi_pet_layout_enabled = False
            self.dual_pet_layout.hide_companion()
            self._refresh_dual_layout_actions()
            return
        pet = self.local_store.get_pet(companion_id)
        if pet is None:
            self.settings.multi_pet_layout_enabled = False
            self.dual_pet_layout.hide_companion()
            self._refresh_dual_layout_actions()
            return
        selection = self.asset_catalog.selection_for(pet)
        self.settings.multi_pet_companion_pet_id = companion_id
        self.dual_pet_layout.show_companion(
            pet_id=companion_id,
            pet_name=pet.identity.name,
            manifest_path=selection.manifest_path,
            display_height=self.settings.display_height,
            use_saved_position=use_saved_position,
        )
        self._refresh_dual_layout_actions()

    def _activate_companion_pet(self, pet_id: str) -> None:
        previous = self.active_pet.identity.pet_id
        if pet_id == previous:
            return
        self.settings.multi_pet_companion_pet_id = previous
        self._switch_rotation_pet(pet_id)

    def _refresh_dual_layout_actions(self) -> None:
        total = len(self.multi_pet_items())
        visible = self.dual_pet_layout.visible
        enabled = bool(self.settings.multi_pet_layout_enabled and visible)
        self.dual_pet_action.setEnabled(total >= 2)
        self.dual_pet_action.setChecked(enabled)
        self.restore_dual_layout_action.setEnabled(total >= 2)
        self.arrange_dual_layout_action.setEnabled(total >= 2)
        self.hide_companion_action.setEnabled(visible)
        companion = self.dual_pet_layout.companion_window
        if companion is not None:
            self.dual_pet_action.setText(f"双宠并排展示（{companion.pet_name}）")
        else:
            self.dual_pet_action.setText("双宠并排展示")

    def _pets_changed(self) -> None:
        previous = self.active_pet.identity.pet_id
        super()._pets_changed()
        current = self.active_pet.identity.pet_id
        if previous != current and self.settings.multi_pet_layout_enabled:
            if self.settings.multi_pet_companion_pet_id == current:
                self.settings.multi_pet_companion_pet_id = previous
            QTimer.singleShot(200, lambda: self._sync_dual_pet_layout(use_saved_position=True))
        self._layout_active_pet_id = current
        self._refresh_dual_layout_actions()

    def _multi_pet_received(self, payload: object) -> None:
        super()._multi_pet_received(payload)
        if self.settings.multi_pet_layout_enabled:
            QTimer.singleShot(100, lambda: self._sync_dual_pet_layout(use_saved_position=True))
        self._refresh_dual_layout_actions()

    def quit(self) -> None:
        if self._quitting:
            return
        self.next_pet_prompt.close()
        self.dual_pet_layout.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return MultiPetCareLayoutApplication().start(smoke_test_ms=smoke_test_ms)
