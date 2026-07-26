"""Desktop composition layer for growth goals and milestone memories."""

from __future__ import annotations

from .desktop_experience import snapshot_stats
from .desktop_experience_app import DesktopExperienceApplication
from .growth_experience import (
    apply_growth_levels,
    build_growth_milestones,
    build_growth_progress,
    build_local_memories,
)
from .growth_experience_client import GrowthExperienceCloudClient
from .pet_registry import LOCAL_ACCOUNT_ID


_LOCAL_GROWTH_GAINS = {
    "feed": (4, 2),
    "play": (7, 4),
    "clean": (3, 2),
    "pet": (2, 3),
    "rest": (1, 1),
}


class GrowthExperienceApplication(DesktopExperienceApplication):
    """Add clear next-stage goals and a reusable growth memory timeline."""

    def __init__(self, *args, **kwargs) -> None:
        self._cloud_growth_experience: dict[str, object] | None = None
        self._cloud_growth_pet_id = ""
        self._pending_growth_stage: dict[str, str] = {}
        super().__init__(*args, **kwargs)
        self.growth_experience_client = GrowthExperienceCloudClient(
            self.cloud_api,
            parent=self.qt_app,
        )
        self.growth_experience_client.experience_received.connect(
            self._growth_experience_received
        )
        self.growth_experience_client.request_failed.connect(
            self._growth_experience_failed
        )
        self.bubble_menu.about_to_show.connect(self._request_cloud_growth_experience)
        self.cloud_session.state_changed.connect(self._growth_cloud_state_changed)

    @staticmethod
    def _stage_value(pet) -> str:
        stage = pet.stats.growth_stage
        return str(getattr(stage, "value", stage))

    def _request_pet_care(self, action: str) -> None:
        normalized = action.strip().lower()
        self._pending_growth_stage[normalized] = self._stage_value(self.active_pet)
        super()._request_pet_care(normalized)

    def _request_cloud_growth_experience(self) -> None:
        pet = self.active_pet
        if (
            pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID
            or not self.cloud_session.connected
        ):
            self._sync_growth_widgets()
            return
        self.growth_experience_client.refresh(pet.identity.pet_id, limit=30)

    def _growth_cloud_state_changed(self, state: str) -> None:
        if state == "connected":
            self._request_cloud_growth_experience()

    def _growth_experience_received(self, pet_id: str, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self._cloud_growth_pet_id = pet_id
        self._cloud_growth_experience = dict(payload)
        if pet_id == self.active_pet.identity.pet_id:
            self._refresh_quick_panel()
            self._sync_growth_widgets()

    def _growth_experience_failed(self, pet_id: str, _message: str) -> None:
        if pet_id == self._cloud_growth_pet_id:
            self._cloud_growth_pet_id = ""
            self._cloud_growth_experience = None
        self._sync_growth_widgets()

    def _local_growth_experience(self) -> dict[str, object]:
        pet = self.active_pet
        if pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID:
            return {"progress": build_growth_progress(pet), "memories": []}

        before = (
            int(pet.stats.growth_level),
            int(pet.stats.bond_level),
            self._stage_value(pet),
        )
        apply_growth_levels(pet)
        after = (
            int(pet.stats.growth_level),
            int(pet.stats.bond_level),
            self._stage_value(pet),
        )
        if after != before:
            try:
                self.local_store.upsert_pet(pet)
            except (OSError, RuntimeError, ValueError):
                pass
        records = self.local_store.list_interaction_records(
            pet.identity.pet_id,
            limit=1000,
        )
        return {
            "progress": build_growth_progress(pet),
            "memories": build_local_memories(records, pet_name=pet.identity.name),
        }

    def _growth_experience(self) -> dict[str, object]:
        if (
            self.active_pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID
            and self._cloud_growth_pet_id == self.active_pet.identity.pet_id
            and isinstance(self._cloud_growth_experience, dict)
        ):
            return self._cloud_growth_experience
        return self._local_growth_experience()

    def _sync_growth_widgets(self) -> None:
        if self._care_panel is None:
            return
        data = self._growth_experience()
        progress = data.get("progress")
        memories = data.get("memories")
        self._care_panel.set_growth_experience(
            progress if isinstance(progress, dict) else None,
            memories if isinstance(memories, list) else None,
        )

    def _refresh_quick_panel(self) -> None:
        super()._refresh_quick_panel()
        data = self._growth_experience()
        progress = data.get("progress")
        if not isinstance(progress, dict):
            return
        current = self.bubble_menu.hint_label.text().strip()
        headline = str(progress.get("headline") or "继续陪伴即可成长")
        remaining = max(
            0,
            int(
                progress.get("next_stage_exp_remaining")
                or progress.get("growth_exp_remaining")
                or 0
            ),
        )
        growth_hint = f"{headline} · 还差 {remaining} 点成长经验"
        self.bubble_menu.hint_label.setText(
            f"{current}\n{growth_hint}" if current else growth_hint
        )
        self._sync_growth_widgets()

    def open_pet_care_panel(self) -> None:
        super().open_pet_care_panel()
        self._sync_growth_widgets()
        self._request_cloud_growth_experience()

    def _align_local_growth_gain(self, action: str) -> None:
        """The base local demo adds +2/+1; adjust it to the server action table."""

        target_growth, target_bond = _LOCAL_GROWTH_GAINS.get(action, (2, 1))
        self.active_pet.stats.growth_exp = max(
            0,
            int(self.active_pet.stats.growth_exp) + target_growth - 2,
        )
        self.active_pet.stats.bond_exp = max(
            0,
            int(self.active_pet.stats.bond_exp) + target_bond - 1,
        )

    def _present_enhanced_care_success(self, action: str) -> None:
        before = dict(
            self._pending_care_before.get(action, snapshot_stats(self.active_pet))
        )
        previous_stage = self._pending_growth_stage.pop(
            action,
            self._stage_value(self.active_pet),
        )
        local_pet = self.active_pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID
        if local_pet:
            self._align_local_growth_gain(action)
            apply_growth_levels(self.active_pet)
            try:
                self.local_store.upsert_pet(self.active_pet)
            except (OSError, RuntimeError, ValueError):
                pass
        after = snapshot_stats(self.active_pet)
        current_stage = self._stage_value(self.active_pet)
        milestones = build_growth_milestones(
            pet_name=self.active_pet.identity.name,
            before=before,
            after=after,
            previous_stage=previous_stage,
            current_stage=current_stage,
        )

        super()._present_enhanced_care_success(action)

        if local_pet:
            for memory in milestones:
                try:
                    self.local_store.save_interaction_record(
                        pet_id=self.active_pet.identity.pet_id,
                        action_type=str(memory["memory_type"]),
                        action_name=str(memory["title"]),
                        detail=str(memory["detail"]),
                        source="growth",
                    )
                except (OSError, RuntimeError, ValueError):
                    pass
        self._sync_growth_widgets()
        self._request_cloud_growth_experience()

    def _pet_care_failed(self, action: str, message: str) -> None:
        self._pending_growth_stage.pop(action, None)
        super()._pet_care_failed(action, message)

    def _pets_changed(self) -> None:
        previous_id = self.active_pet.identity.pet_id
        super()._pets_changed()
        if self.active_pet.identity.pet_id != previous_id:
            self._cloud_growth_pet_id = ""
            self._cloud_growth_experience = None
        self._sync_growth_widgets()
        if self.bubble_menu.isVisible():
            self._request_cloud_growth_experience()


def run(smoke_test_ms: int | None = None) -> int:
    return GrowthExperienceApplication().start(smoke_test_ms=smoke_test_ms)
