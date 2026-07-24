from __future__ import annotations

import json
import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

import pytest
from PIL import Image

from onepic_desktop_pet.domain import PetIdentity, PetProfile
from onepic_desktop_pet.pet_assets import (
    PetAssetCatalog,
    PetAssetIdentity,
    load_pet_asset_manifest,
)
from onepic_desktop_pet.resources import resource_path


def _profile(
    template_id: str,
    identity_version: str,
    asset_version: str,
) -> PetProfile:
    return PetProfile(
        identity=PetIdentity(
            pet_id=f"pet-{template_id}",
            name=template_id,
            template_id=template_id,
            template_version="1.0.0",
            identity_version=identity_version,
            primary_owner_account_id="account-1",
        ),
        asset_version=asset_version,
        updated_at=datetime.now().astimezone(),
    )


def _single_frame_manifest(path, *, template_id="cached.pet") -> None:
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(path.parent / "frame.png")
    path.write_text(
        json.dumps(
            {
                "schema_version": "2.1",
                "template_id": template_id,
                "identity_version": "1.0.0",
                "asset_version": "3.0.0",
                "animations": {"idle": ["frame.png"]},
                "fallback_actions": {
                    "walk": "idle",
                    "sit": "idle",
                    "sleep": "idle",
                    "wave": "idle",
                    "happy": "idle",
                    "shy": "idle",
                    "surprised": "idle",
                    "annoyed": "idle",
                    "sleepy": "idle",
                    "curious": "idle",
                    "selfie": "idle",
                    "drag": "idle"
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_manifest_rejects_parent_directory_escape(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "2.1",
                "template_id": "unsafe",
                "identity_version": "1.0.0",
                "asset_version": "1.0.0",
                "animations": {"idle": ["../escape.png"]},
                "fallback_actions": {
                    name: "idle"
                    for name in (
                        "walk", "sit", "sleep", "wave", "happy", "shy",
                        "surprised", "annoyed", "sleepy", "curious", "selfie", "drag"
                    )
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="安全的包内相对路径"):
        load_pet_asset_manifest(manifest)


def test_catalog_installs_and_prefers_exact_cached_package(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source_manifest = source / "package.json"
    _single_frame_manifest(source_manifest)

    catalog = PetAssetCatalog(
        cache_root=tmp_path / "cache",
        bundled_manifest_paths=[resource_path("assets/pet/manifest.json")],
    )
    identity = PetAssetIdentity("cached.pet", "1.0.0", "3.0.0")
    installed = catalog.install_package(source_manifest, expected=identity)

    assert installed.is_file()
    selection = catalog.selection_for(_profile(*identity.key))
    assert selection.exact
    assert selection.source == "cache"
    assert selection.manifest_path == installed.resolve()


def test_bundled_sun_sun_spritesheet_loads_every_runtime_state() -> None:
    from PySide6.QtWidgets import QApplication

    from onepic_desktop_pet.behavior import PetState
    from onepic_desktop_pet.pet_assets import load_pet_asset_bundle

    app = QApplication.instance() or QApplication([])
    manifest_path = resource_path("outputs/sun-sun/manifest.json")
    bundle = load_pet_asset_bundle(manifest_path)

    assert bundle.manifest.identity.key == ("sun-sun", "1.0.0", "2.0.0")
    assert set(bundle.pixmaps) == set(PetState)
    assert len(bundle.pixmaps[PetState.WALK]) == 8
    assert bundle.pixmaps[PetState.IDLE][0].width() == 192
    assert bundle.pixmaps[PetState.IDLE][0].height() == 208
    assert not bundle.pixmaps[PetState.HAPPY][0].isNull()
    app.processEvents()


def test_dynamic_window_hot_switches_after_full_package_validation() -> None:
    from PySide6.QtWidgets import QApplication

    from onepic_desktop_pet.behavior import PetState
    from onepic_desktop_pet.config import PetSettings
    from onepic_desktop_pet.dynamic_window import DynamicPetWindow

    app = QApplication.instance() or QApplication([])
    demo = resource_path("assets/pet/manifest.json")
    sun_sun = resource_path("outputs/sun-sun/manifest.json")
    window = DynamicPetWindow(PetSettings(), demo)
    original_position = window.pos()

    window.load_pet_assets(sun_sun)

    assert window.loaded_asset_manifest_path == sun_sun.resolve()
    assert len(window._pixmaps[PetState.IDLE]) == 7
    assert len(window._pixmaps[PetState.WALK]) == 8
    assert window.pos() == original_position
    assert window.state in PetState
    window.close()
    window.deleteLater()
    app.processEvents()
