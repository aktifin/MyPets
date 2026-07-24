"""Asset-aware PetWindow that atomically hot-swaps validated frame or spritesheet packages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint

from .behavior import PetState
from .config import PetSettings
from .pet_assets import PetAssetBundle, load_pet_asset_bundle
from .window import PetWindow


class DynamicPetWindow(PetWindow):
    """Preserve the existing behavior state machine while allowing runtime asset replacement."""

    def __init__(
        self,
        settings: PetSettings,
        asset_manifest_path: Path | None = None,
    ) -> None:
        self._requested_asset_manifest_path = asset_manifest_path
        self._loaded_asset_manifest_path: Path | None = None
        self._loaded_asset_bundle: PetAssetBundle | None = None
        super().__init__(settings)

    @property
    def loaded_asset_manifest_path(self) -> Path | None:
        return self._loaded_asset_manifest_path

    def _load_pixmaps(self):
        if self._requested_asset_manifest_path is None:
            self._loaded_asset_manifest_path = None
            self._loaded_asset_bundle = None
            return super()._load_pixmaps()
        bundle = load_pet_asset_bundle(self._requested_asset_manifest_path)
        self._loaded_asset_bundle = bundle
        self._loaded_asset_manifest_path = bundle.manifest.path
        self._walk_motion_factors = bundle.manifest.walk_motion_factors
        return dict(bundle.pixmaps)

    def show_care_feedback(self, action: str) -> None:
        """Map confirmed server care actions onto existing local animations."""

        mapping = {
            "feed": PetState.HAPPY,
            "play": PetState.WAVE,
            "clean": PetState.SHY,
            "pet": PetState.HAPPY,
            "rest": PetState.SLEEPY,
        }
        self._show_emotion(mapping.get(action, PetState.HAPPY), 1700)

    def trigger_care_feedback(self, action: str) -> None:
        """Compatibility alias for callers using the newer verb-oriented name."""

        self.show_care_feedback(action)

    def trigger_growth_feedback(self, event_type: str) -> None:
        """Celebrate confirmed level, bond, or stage transitions without new assets."""

        state = PetState.SURPRISED if event_type == "growth_stage_changed" else PetState.HAPPY
        self._show_emotion(state, 2400 if event_type == "growth_stage_changed" else 1900)

    def load_pet_assets(self, manifest_path: Path | None) -> None:
        """Load an entire package before mutating visible state, then switch from an idle frame."""

        requested = Path(manifest_path).resolve() if manifest_path is not None else None
        if requested == self._loaded_asset_manifest_path and not (
            requested is None and self._loaded_asset_manifest_path is not None
        ):
            return

        if requested is None:
            previous_request = self._requested_asset_manifest_path
            self._requested_asset_manifest_path = None
            try:
                pixmaps = super()._load_pixmaps()
            except Exception:
                self._requested_asset_manifest_path = previous_request
                raise
            bundle = None
            motion_factors = self._walk_motion_factors
        else:
            bundle = load_pet_asset_bundle(requested)
            pixmaps = dict(bundle.pixmaps)
            motion_factors = bundle.manifest.walk_motion_factors

        old_position = QPoint(self.pos())
        self.animation_timer.stop()
        self.state_timer.stop()
        self.turn_timer.stop()
        self.interaction_timer.stop()
        self.effect_timer.stop()

        self._pixmaps = pixmaps
        self._walk_motion_factors = motion_factors
        self._loaded_asset_bundle = bundle
        self._loaded_asset_manifest_path = bundle.manifest.path if bundle else None
        self._requested_asset_manifest_path = requested
        self._render_cache.clear()
        self._mask_cache.clear()

        source = self._pixmaps[PetState.IDLE][0]
        width = round(self.settings.display_height * source.width() / source.height())
        self.setFixedSize(width + 12, self.settings.display_height + 14)
        self.label.setGeometry(6, 0, width, self.settings.display_height + 8)
        self.move(self._constrained_position(old_position))
        self.set_state(PetState.IDLE)
        self._schedule(self.behavior.initial_idle())
