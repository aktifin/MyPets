"""Tests for current revoked asset snapshots used by newly bound devices."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from .test_asset_revocation_acknowledgements import (
    _device_auth,
    _published_revoked_release,
)
from .test_governance import _register, governance_client


def test_new_device_can_list_current_revoked_asset_identity(
    governance_client: TestClient,
) -> None:
    client = governance_client
    context = _published_revoked_release(client)
    owner_auth = {"Authorization": context["owner_header"]}
    device_auth, _device_id = _device_auth(
        client, owner_auth, f"revocation-snapshot-device-{uuid4()}"
    )

    notices = client.get("/api/v1/asset-revocations", headers=device_auth)

    assert notices.status_code == 200, notices.text
    assert len(notices.json()) == 1
    notice = notices.json()[0]
    assert notice["right_id"] == context["right_id"]
    assert notice["artifact_id"] == context["artifact_id"]
    assert notice["release_id"] == context["release_id"]
    assert notice["pet_id"] == context["pet_id"]
    assert notice["action"] == "evict_cache_and_fallback"
    assert notice["asset_identity"] == {
        "template_id": "governance.cat.ack",
        "identity_version": "1.0.0",
        "asset_version": "1.0.0",
    }


def test_revoked_asset_snapshot_requires_device_scope(
    governance_client: TestClient,
) -> None:
    client = governance_client
    context = _published_revoked_release(client)
    owner_auth = {"Authorization": context["owner_header"]}
    account_request = client.get("/api/v1/asset-revocations", headers=owner_auth)
    assert account_request.status_code == 403, account_request.text

    stranger = _register(client, "snapshot_stranger")
    stranger_device, _device_id = _device_auth(
        client, stranger, f"snapshot-stranger-{uuid4()}"
    )
    notices = client.get("/api/v1/asset-revocations", headers=stranger_device)
    assert notices.status_code == 200, notices.text
    assert notices.json() == []
