"""Customer-experience composition root for the Windows desktop pet."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSystemTrayIcon

from .config import save_settings
from .desktop_experience import (
    CARE_ACTION_LABELS,
    apply_local_demo_care,
    daily_care_progress,
    format_care_result,
    plain_status_summary,
    recommend_care,
    snapshot_stats,
)
from .desktop_feedback import DesktopFeedbackToast
from .first_run_dialog import FirstRunDialog
from .pet_registry import LOCAL_ACCOUNT_ID
from .tray_app import TrayDesktopPetApplication


DESKTOP_EXPERIENCE_VERSION = 1
_STAGE_LABELS = {
    "newborn": "初生期",
    "child": "幼年期",
    "juvenile": "成长期",
    "adult": "成熟期",
    "bond": "羁绊期",
}
_PRESENCE_LABELS = {
    "home": "在家",
    "visiting": "串门中",
    "away": "外出",
}


class DesktopExperienceApplication(TrayDesktopPetApplication):
    """Add the first-run and daily-care experience without changing cloud authority."""

    def __init__(self, *args, **kwargs) -> None:
        self._pending_care_before: dict[str, dict[str, int]] = {}
        self._first_run_dialog: FirstRunDialog | None = None
        super().__init__(*args, **kwargs)
        self._feedback_toast = DesktopFeedbackToast()
        self.bubble_menu.about_to_show.connect(self._refresh_quick_panel)

        self.guide_action = QAction("重新查看新手引导…", self.system_tray_menu.pets_root_menu)
        self.guide_action.triggered.connect(self.open_first_run_dialog)
        self.system_tray_menu.pets_root_menu.addSeparator()
        self.system_tray_menu.pets_root_menu.addAction(self.guide_action)

    def _on_bubble_action(self, action_code: str) -> None:
        action = "pet" if action_code == "touch" else action_code
        if action in CARE_ACTION_LABELS:
            self._request_pet_care(action)
        elif action_code == "chat":
            self.open_pet_chat_dialog()
        elif action_code == "checkin":
            self.open_health_analytics_dialog()
        elif action_code == "stats":
            self.open_pet_care_panel()

    def _refresh_quick_panel(self) -> None:
        pet = self.active_pet
        recommendation = recommend_care(pet)
        records = self.local_store.list_interaction_records(pet.identity.pet_id, limit=100)
        daily_count, daily_goal = daily_care_progress(records)
        presence = getattr(pet.presence, "value", str(pet.presence))
        local_pet = pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID
        can_care = presence == "home" and (local_pet or self.cloud_session.connected)
        detail = recommendation.detail
        if not local_pet and not self.cloud_session.connected and presence == "home":
            detail = "云端未连接，连接恢复后才能提交照料。"
        stage = getattr(pet.stats.growth_stage, "value", str(pet.stats.growth_stage))
        self.bubble_menu.set_context(
            pet_name=pet.identity.name,
            level_text=(
                f"Lv.{pet.stats.growth_level} · {_STAGE_LABELS.get(stage, stage)} · "
                f"羁绊 Lv.{pet.stats.bond_level}"
            ),
            presence_text=_PRESENCE_LABELS.get(presence, presence),
            status_text=plain_status_summary(pet),
            recommendation_action=recommendation.action,
            recommendation_text=recommendation.title,
            recommendation_detail=detail,
            daily_count=daily_count,
            daily_goal=daily_goal,
            can_care=can_care,
        )

    def _request_pet_care(self, action: str) -> None:
        normalized = action.strip().lower()
        if normalized not in CARE_ACTION_LABELS:
            self._pet_care_failed(normalized, "不支持的照料动作")
            return
        self._pending_care_before[normalized] = snapshot_stats(self.active_pet)
        if self.active_pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID:
            super()._request_pet_care(normalized)
            return

        if self.active_pet.presence.value != "home":
            self._pet_care_failed(normalized, "宠物串门期间不能在本机照料")
            return
        if self._care_panel is not None:
            self._care_panel.set_busy(True, f"正在{CARE_ACTION_LABELS[normalized]}…")
        try:
            updated = apply_local_demo_care(self.active_pet, normalized)
            self.local_store.upsert_pet(updated)
            self.active_pet = updated
            self._refresh_active_pet_ui()
            self._present_enhanced_care_success(normalized)
        except (OSError, RuntimeError, ValueError) as exc:
            self._pet_care_failed(normalized, str(exc))

    def _pet_care_succeeded(self, action: str, payload: object) -> None:
        super()._pet_care_succeeded(action, payload)
        self._present_enhanced_care_success(action)

    def _present_enhanced_care_success(self, action: str) -> None:
        before = self._pending_care_before.pop(action, snapshot_stats(self.active_pet))
        after = snapshot_stats(self.active_pet)
        summary = format_care_result(self.active_pet.identity.name, action, before, after)
        try:
            self.local_store.save_interaction_record(
                pet_id=self.active_pet.identity.pet_id,
                action_type=action,
                action_name=CARE_ACTION_LABELS.get(action, "照料"),
                detail=f"{summary.title}：{summary.detail}",
                source="user",
            )
        except (OSError, RuntimeError, ValueError):
            pass
        self.window.show_care_feedback(action)
        if self._care_panel is not None:
            self._care_panel.set_pet(self.active_pet)
            self._care_panel.show_result(f"{summary.title}：{summary.detail}")
        self._feedback_toast.show_near(
            self.window,
            summary.title,
            summary.detail,
        )
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage(
                summary.title,
                summary.detail,
                QSystemTrayIcon.MessageIcon.Information,
                2600,
            )
        self._refresh_quick_panel()

    def _pet_care_failed(self, action: str, message: str) -> None:
        self._pending_care_before.pop(action, None)
        super()._pet_care_failed(action, message)
        label = CARE_ACTION_LABELS.get(action, "照料")
        self._feedback_toast.show_near(
            self.window,
            f"{label}未完成",
            message,
            error=True,
        )
        self._refresh_quick_panel()

    def open_first_run_dialog(self) -> None:
        if self._first_run_dialog is None:
            dialog = FirstRunDialog()
            dialog.completed.connect(self._complete_first_run)
            dialog.login_requested.connect(self.open_cloud_login)
            self._first_run_dialog = dialog
        self._first_run_dialog.set_pet_name(self.active_pet.identity.name)
        self._first_run_dialog.restart()

    def _complete_first_run(self) -> None:
        if self.settings.desktop_experience_version >= DESKTOP_EXPERIENCE_VERSION:
            return
        self.settings.desktop_experience_version = DESKTOP_EXPERIENCE_VERSION
        try:
            save_settings(self.settings)
        except OSError:
            self.tray.setToolTip(
                f"{self.active_pet.identity.name} · 新手引导完成，但设置暂未保存"
            )

    def _pets_changed(self) -> None:
        super()._pets_changed()
        if self._first_run_dialog is not None:
            self._first_run_dialog.set_pet_name(self.active_pet.identity.name)
        if self.bubble_menu.isVisible():
            self._refresh_quick_panel()

    def start(self, smoke_test_ms: int | None = None) -> int:
        if (
            smoke_test_ms is None
            and self.settings.desktop_experience_version < DESKTOP_EXPERIENCE_VERSION
        ):
            QTimer.singleShot(450, self.open_first_run_dialog)
        return super().start(smoke_test_ms=smoke_test_ms)

    def quit(self) -> None:
        if self._quitting:
            return
        if self._first_run_dialog is not None:
            self._first_run_dialog.close()
        self._feedback_toast.close()
        self.bubble_menu.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return DesktopExperienceApplication().start(smoke_test_ms=smoke_test_ms)
