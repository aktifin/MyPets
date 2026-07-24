from __future__ import annotations

import pytest

from onepic_desktop_pet.cloud_types import (
    DeviceCredentials,
    credential_target,
    normalize_base_url,
)
from onepic_desktop_pet.credential_store import MemoryCredentialStore


def test_normalize_base_url_rejects_unsafe_components() -> None:
    assert normalize_base_url(" HTTPS://pets.example.com/api/ ") == "https://pets.example.com/api"
    with pytest.raises(ValueError):
        normalize_base_url("ftp://pets.example.com")
    with pytest.raises(ValueError):
        normalize_base_url("https://user:secret@pets.example.com")
    with pytest.raises(ValueError):
        normalize_base_url("https://pets.example.com?token=secret")


def test_device_credentials_are_isolated_by_server_origin() -> None:
    first = DeviceCredentials(
        "https://one.example.com/",
        "account-1",
        "device-1",
        "x" * 32,
    )
    second = DeviceCredentials(
        "https://two.example.com",
        "account-2",
        "device-2",
        "y" * 32,
    )
    store = MemoryCredentialStore()
    store.save(first)
    store.save(second)

    assert store.load("https://one.example.com") == first
    assert store.load("https://two.example.com/") == second
    assert credential_target(first.base_url) != credential_target(second.base_url)
    assert "one.example.com" not in credential_target(first.base_url)


def test_device_secret_is_never_optional_or_short() -> None:
    with pytest.raises(ValueError):
        DeviceCredentials("https://pets.example.com", "a", "d", "short")
