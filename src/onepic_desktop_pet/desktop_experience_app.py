"""Customer-experience composition root for the Windows desktop pet."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSystemTrayIcon

from .config import save_settings
from .daily_care_client import DailyCareCloudClient
from .desktop_experience import (
    CARE_ACTION_LABELS,
    apply_local_demo_care,
    build_local_daily_care_summary,
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
    """Add first-run guidance and a cross-device daily care experience."""

    def __init__(self, *args, **kwargs) -> None:
        self._pending_care_before: dict[str, dict[str, int]] = {}
        self._first_run_dialog: FirstRunDialog | None = None
        self._cloud_daily_summary: dict[str, object] | None = None
        self._cloud_daily_pet_id = ""
        super().__init__(*args, **kwargs)
        self._feedback_toast = DesktopFeedbackToast()
        self.daily_care_client = DailyCareCloudClient(
            self.cloud_api,
            parent=self.qt_app,
        )
        self.daily_care_client.summary_received.connect(self._daily_care_received)
        self.daily_care_client.request_failed.connect(self._daily_care_failed)
        self.bubble_menu.about_to_show.connect(self._quick_panel_opening)

        self._daily_refresh_timer = QTimer(self.qt_app)
        self._daily_refresh_timer.setInterval(1000)
        self._daily_refresh_timer.timeout.connect(self._refresh_visible_quick_panel)
        self._daily_refresh_timer.start()

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

    @staticmethod
    def _timezone_offset_minutes() -> int:
        offset = datetime.now().astimezone().utcoffset()
        return -round((offset.total_seconds() if offset else 0) / 60)

    def _quick_panel_opening(self) -> None:
        self._refresh_quick_panel()
        self._request_cloud_daily_summary()

    def _request_cloud_daily_summary(self) -> None:
        pet = self.active_pet
        if (
            pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID
            or not self.cloud_session.connected
        ):
            return
        self.daily_care_client.refresh(
            pet.identity.pet_id,
            self._timezone_offset_minutes(),
        )

    def _daily_care_received(self, pet_id: str, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self._cloud_daily_pet_id = pet_id
        self._cloud_daily_summary = dict(payload)
        if pet_id == self.active_pet.identity.pet_id:
            self._refresh_quick_panel()

    def _daily_care_failed(self, pet_id: str, _message: str) -> None:
        if pet_id == self._cloud_daily_pet_id:
            self._cloud_daily_pet_id = ""
            self._cloud_daily_summary = None
        if self.bubble_menu.isVisible():
            self._refresh_quick_panel()

    def _local_daily_summary(self) -> dict[str, object]:
        records = self.local_store.list_interaction_records(
            self.active_pet.identity.pet_id,
            limit=1000,
        )
        return build_local_daily_care_summary(records)

    def _daily_summary(self) -> dict[str, object]:
        if (
            self.active_pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID
            and self._cloud_daily_pet_id == self.active_pet.identity.pet_id
            and isinstance(self._cloud_daily_summary, dict)
        ):
            return self._cloud_daily_summary
        return self._local_daily_summary()

    @staticmethod
    def _action_state(
        summary: dict[str, object],
        action: str,
    ) -> tuple[bool, str]:
        values = summary.get("actions")
        for raw in values if isinstance(values, list) else []:
            if not isinstance(raw, dict) or raw.get("action") != action:
                continue
            next_at = raw.get("next_available_at")
            remaining = max(0, int(raw.get("remaining_seconds") or 0))
            if isinstance(next_at, str) and next_at:
                try:
                    parsed = datetime.fromisoformat(next_at.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    remaining = max(
                        0,
                        math.ceil((parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds()),
                    )
                except ValueError:
                    pass
            if bool(summary.get("daily_limit_reached")):
                limit = int(summary.get("daily_limit") or 50)
                return False, f"今天已完成 {limit} 次照料，明天可以继续。"
            if remaining > 0:
                label = str(raw.get("label") or CARE_ACTION_LABELS.get(action, "照料"))
                return False, f"{label}刚刚完成，{remaining} 秒后可再次操作。"
            return bool(raw.get("available", True)), str(
                raw.get("reason") or "现在可以操作。"
            )
        return True, "现在可以操作。"

    @staticmethod
    def _task_text(summary: dict[str, object]) -> str:
        parts: list[str] = []
        tasks = summary.get("tasks")
        for raw in tasks if isinstance(tasks, list) else []:
            if not isinstance(raw, dict):
                continue
            marker = "✓" if raw.get("completed") else f"{raw.get('current', 0)}/{raw.get('target', 1)}"
            parts.append(f"{marker} {raw.get('title', '今日任务')}")
        return "  ·  ".join(parts)

    def _refresh_visible_quick_panel(self) -> None:
        if self.bubble_menu.isVisible():
            self._refresh_quick_panel()

    def _refresh_quick_panel(self) -> None:
        pet = self.active_pet
        recommendation = recommend_care(pet)
        summary = self._daily_summary()
        presence = getattr(pet.presence, "value", str(pet.presence))
        local_pet = pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID
        can_care = presence == "home" and (local_pet or self.cloud_session.connected)
        detail = recommendation.detail
        if not local_pet and not self.cloud_session.connected and presence == "home":
            detail = "云端未连接，连接恢复后才能提交照料。"
        action_states = {
            action: self._action_state(summary, action)
            for action in CARE_ACTION_LABELS
        }
        if not can_care:
            reason = detail
            action_states = {action: (False, reason) for action in CARE_ACTION_LABELS}
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
            daily_count=int(summary.get("completed_tasks") or 0),
            daily_goal=int(summary.get("total_tasks") or 3),
            can_care=can_care,
            streak_days=int(summary.get("streak_days") or 0),
            task_text=self._task_text(summary),
            reward_text=str(summary.get("reward_detail") or "完成全部任务可点亮今日陪伴徽章。"),
            action_states=action_states,
        )

    def _request_pet_care(self, action: str) -> None:
        normalized = action.strip().lower()
        if normalized not in CARE_ACTION_LABELS:
            self._pet_care_failed(normalized, "不支持的照料动作")
            return
        available, reason = self._action_state(self._daily_summary(), normalized)
        if not available:
            self._pet_care_failed(normalized, reason)
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

    def _pet_care_succeeded(self, action: str, _payload: object) -> None:
        active = self.pet_registry.active_pet()
        if active is not None:
            self.active_pet = active
        self._refresh_active_pet_ui()
        self._present_enhanced_care_success(action)

    def _present_enhanced_care_success(self, action: str) -> None:
        before = self._pending_care_before.pop(action, snapshot_stats(self.active_pet))
        after = snapshot_stats(self.active_pet)
        result = format_care_result(self.active_pet.identity.name, action, before, after)
        try:
            self.local_store.save_interaction_record(
                pet_id=self.active_pet.identity.pet_id,
                action_type=action,
                action_name=CARE_ACTION_LABELS.get(action, "照料"),
                detail=f"{result.title}：{result.detail}",
                source="user",
            )
        except (OSError, RuntimeError, ValueError):
            pass
        self.window.show_care_feedback(action)
        if self._care_panel is not None:
            self._care_panel.set_pet(self.active_pet)
            self._care_panel.show_result(f"{result.title}：{result.detail}")
        local_summary = self._local_daily_summary()
        task_detail = str(local_summary.get("reward_detail") or "")
        toast_detail = f"{result.detail}\n{task_detail}" if task_detail else result.detail
        self._feedback_toast.show_near(
            self.window,
            result.title,
            toast_detail,
        )
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage(
                result.title,
                toast_detail,
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        self._refresh_quick_panel()
        self._request_cloud_daily_summary()

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
        previous_id = self.active_pet.identity.pet_id
        super()._pets_changed()
        if self.active_pet.identity.pet_id != previous_id:
            self._cloud_daily_pet_id = ""
            self._cloud_daily_summary = None
        if self._first_run_dialog is not None:
            self._first_run_dialog.set_pet_name(self.active_pet.identity.name)
        if self.bubble_menu.isVisible():
            self._refresh_quick_panel()
            self._request_cloud_daily_summary()

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
        self._daily_refresh_timer.stop()
        if self._first_run_dialog is not None:
            self._first_run_dialog.close()
        self._feedback_toast.close()
        self.bubble_menu.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    return DesktopExperienceApplication().start(smoke_test_ms=smoke_test_ms)
