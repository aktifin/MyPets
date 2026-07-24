from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

import pytest
from PIL import Image

from onepic_desktop_pet.asset_download import (
    AssetReleaseMetadata,
    install_asset_package_zip,
)
from onepic_desktop_pet.domain import PetIdentity, PetProfile
from onepic_desktop_pet.pet_assets import PetAssetCatalog
from onepic_desktop_pet.resources import resource_path


def _profile() -> PetProfile:
    return PetProfile(
        identity=PetIdentity(
            pet_id="cloud-pet-1",
            name="云端猫",
            template_id="official.cat.cloud",
            template_version="1.0.0",
            identity_version="1.0.0",
            primary_owner_account_id="account-1",
        ),
        asset_version="2.0.0",
        updated_at=datetime.now().astimezone(),
    )


def _package() -> bytes:
    image_buffer = io.BytesIO()
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(image_buffer, format="PNG")
    frame = image_buffer.getvalue()
    manifest = {
        "schema_version": "2.1",
        "template_id": "official.cat.cloud",
        "identity_version": "1.0.0",
        "asset_version": "2.0.0",
        "animations": {"idle": ["frame.png"]},
        "fallback_actions": {
            name: "idle"
            for name in (
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
        },
        "files": [
            {
                "path": "frame.png",
                "size": len(frame),
                "sha256": hashlib.sha256(frame).hexdigest(),
            }
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("frame.png", frame)
    return output.getvalue()


def _metadata(data: bytes, *, download_url: str = "/api/v1/assets/releases/release-1/package") -> AssetReleaseMetadata:
    return AssetReleaseMetadata.from_payload(
        {
            "release_id": "release-1",
            "template_id": "official.cat.cloud",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "2.0.0",
            "package_sha256": hashlib.sha256(data).hexdigest(),
            "package_size": len(data),
            "download_url": download_url,
            "manifest": {
                "schema_version": "2.1",
                "template_id": "official.cat.cloud",
            },
        }
    )


def test_release_metadata_rejects_cross_origin_download_url() -> None:
    data = _package()
    with pytest.raises(ValueError, match="同源相对路径"):
        _metadata(data, download_url="https://evil.example/package.zip")


def test_downloaded_zip_is_verified_and_installed_into_exact_cache(tmp_path) -> None:
    data = _package()
    catalog = PetAssetCatalog(
        cache_root=tmp_path / "cache",
        bundled_manifest_paths=[resource_path("assets/pet/manifest.json")],
    )
    assert not catalog.selection_for(_profile()).exact

    installed = install_asset_package_zip(data, _metadata(data), catalog)

    assert installed.is_file()
    selection = catalog.selection_for(_profile())
    assert selection.exact
    assert selection.source == "cache"
    assert selection.manifest_path == installed.resolve()
    assert not (catalog.cache_root / ".downloads" / "release-1.installing").exists()


def test_downloaded_zip_rejects_hash_mismatch_and_path_escape(tmp_path) -> None:
    data = _package()
    catalog = PetAssetCatalog(
        cache_root=tmp_path / "cache",
        bundled_manifest_paths=[resource_path("assets/pet/manifest.json")],
    )
    payload = _metadata(data)
    bad_hash = AssetReleaseMetadata(
        **{**payload.__dict__, "package_sha256": "0" * 64}
    )
    with pytest.raises(ValueError, match="哈希"):
        install_asset_package_zip(data, bad_hash, catalog)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("../escape.txt", "bad")
    unsafe = output.getvalue()
    unsafe_metadata = AssetReleaseMetadata(
        **{
            **payload.__dict__,
            "package_sha256": hashlib.sha256(unsafe).hexdigest(),
            "package_size": len(unsafe),
        }
    )
    with pytest.raises(ValueError, match="不安全路径"):
        install_asset_package_zip(unsafe, unsafe_metadata, catalog)
