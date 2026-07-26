from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

import pytest
from PIL import Image

from onepic_desktop_pet import asset_download as _asset_download  # noqa: F401
from onepic_desktop_pet.asset_revocation import (
    AssetRevocationTaskStore,
    is_identity_revoked,
    process_asset_revocations,
)
from onepic_desktop_pet.domain import PetIdentity, PetProfile
from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.pet_assets import PetAssetCatalog, PetAssetIdentity
from onepic_desktop_pet.resources import resource_path

_REQUIRED_ACTIONS = (
    "idle",
    "walk",
    "sit",
    "sleep",
    "wave",
    "happy",
    "shy",
    "surprised",
    "annoyed",
    "sleepy",
    "curious",
    "selfie",
    "drag",
)


def _profile(pet_id: str, *, asset_version: str = "2.0.0") -> PetProfile:
    return PetProfile(
        identity=PetIdentity(
            pet_id=pet_id,
            name="撤销测试宠物",
            template_id="custom.revoked.cat",
            template_version=asset_version,
            identity_version=asset_version,
            primary_owner_account_id="account-1",
        ),
        asset_version=asset_version,
        updated_at=datetime.now(UTC),
    )


def _source_package(root: Path, identity: PetAssetIdentity) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    frame = root / "frame.png"
    Image.new("RGBA", (24, 24), (255, 120, 120, 255)).save(frame, format="PNG")
    manifest = {
        "schema_version": "2.1",
        "template_id": identity.template_id,
        "identity_version": identity.identity_version,
        "asset_version": identity.asset_version,
        "animations": {name: ["frame.png"] for name in _REQUIRED_ACTIONS},
        "files": [
            {
                "path": "frame.png",
                "size": frame.stat().st_size,
                "sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
            }
        ],
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _event(profile: PetProfile, *, right_id: str | None = None, release_id: str | None = None) -> dict:
    return {
        "events": [
            {
                "event_id": str(uuid4()),
                "event_type": "asset_revoked",
                "payload": {
                    "cause": "asset_right_revoked",
                    "right_id": right_id or str(uuid4()),
                    "artifact_id": str(uuid4()),
                    "pet_id": profile.identity.pet_id,
                    "release_id": release_id or str(uuid4()),
                    "reason": "授权终止，停止使用本地专属素材。",
                    "action": "evict_cache_and_fallback",
                },
            }
        ]
    }


def test_revocation_evicts_exact_cache_and_permanently_selects_safe_fallback(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.sqlite3")
    profile = _profile(str(uuid4()))
    store.upsert_pet(profile)
    catalog = PetAssetCatalog(
        cache_root=tmp_path / "pet-assets",
        bundled_manifest_paths=[resource_path("assets/pet/manifest.json")],
    )
    identity = PetAssetIdentity(
        profile.identity.template_id,
        profile.identity.identity_version,
        profile.asset_version,
    )
    installed = catalog.install_package(
        _source_package(tmp_path / "source", identity), expected=identity
    )
    assert installed.is_file()
    assert catalog.selection_for(profile).source == "cache"

    tasks = AssetRevocationTaskStore(store)
    assert tasks.queue_from_sync_payload(_event(profile)) == 1
    processed = process_asset_revocations(tasks, [catalog.cache_root])

    assert len(processed) == 1
    assert processed[0].status == "completed"
    assert processed[0].cache_cleared is True
    assert not installed.parent.exists()
    assert is_identity_revoked(catalog.cache_root, identity)
    selection = catalog.selection_for(profile)
    assert selection.source == "fallback-revoked"
    assert selection.exact is False

    with pytest.raises(ValueError, match="已被撤销"):
        catalog.install_package(
            _source_package(tmp_path / "reinstall", identity), expected=identity
        )
    store.close()


def test_revocation_without_downloaded_cache_is_still_completed_and_ackable(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.sqlite3")
    profile = _profile(str(uuid4()), asset_version="3.0.0")
    store.upsert_pet(profile)
    catalog = PetAssetCatalog(
        cache_root=tmp_path / "pet-assets",
        bundled_manifest_paths=[resource_path("assets/pet/manifest.json")],
    )
    tasks = AssetRevocationTaskStore(store)
    payload = _event(profile)
    assert tasks.queue_from_sync_payload(payload) == 1

    processed = process_asset_revocations(tasks, [catalog.cache_root])

    assert processed[0].status == "completed"
    assert processed[0].cache_cleared is True
    assert processed[0].fallback_applied is True
    assert tasks.list_unacknowledged()[0].key == processed[0].key
    tasks.mark_acknowledged(*processed[0].key)
    assert tasks.list_unacknowledged() == []
    store.close()


def test_duplicate_sync_event_does_not_duplicate_cleanup_task(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.sqlite3")
    profile = _profile(str(uuid4()))
    store.upsert_pet(profile)
    tasks = AssetRevocationTaskStore(store)
    right_id, release_id = str(uuid4()), str(uuid4())
    payload = _event(profile, right_id=right_id, release_id=release_id)

    assert tasks.queue_from_sync_payload(payload) == 1
    assert tasks.queue_from_sync_payload(payload) == 0
    assert [task.key for task in tasks.list_processable()] == [(right_id, release_id)]
    store.close()
