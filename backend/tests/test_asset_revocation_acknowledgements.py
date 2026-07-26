"""End-to-end revoked personal asset cleanup acknowledgement tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from .test_governance import (
    _create_pet,
    _create_template_version,
    _register,
    _seed_ready_artifact,
    governance_client,
)


def _device_auth(client: TestClient, account_auth: dict[str, str], public_id: str) -> tuple[dict[str, str], str]:
    bound = client.post(
        "/api/v1/devices/bind",
        headers=account_auth,
        json={"public_id": public_id, "name": "撤销回执测试设备", "platform": "windows"},
    )
    assert bound.status_code == 201, bound.text
    payload = bound.json()
    token = client.post(
        "/api/v1/auth/device-token",
        json={
            "device_id": payload["device"]["id"],
            "device_secret": payload["device_secret"],
        },
    )
    assert token.status_code == 200, token.text
    return {"Authorization": f"Bearer {token.json()['access_token']}"}, payload["device"]["id"]


def _published_revoked_release(client: TestClient) -> dict[str, str]:
    owner = _register(client, "ack_owner")
    editor = _register(client, "gov_editor")
    reviewer = _register(client, "gov_reviewer")
    publisher = _register(client, "gov_publisher")
    template_code = "governance.cat.ack"
    pet_id = _create_pet(client, owner, template_code)
    version_id = _create_template_version(client, editor, template_code)
    job_id, artifact_id = _seed_ready_artifact(
        client,
        owner_username="ack_owner",
        uploader_username="gov_editor",
        pet_id=pet_id,
        template_version_id=version_id,
        template_code=template_code,
    )
    declared = client.post(
        "/api/v1/admin/governance/rights",
        headers=editor,
        json={
            "artifact_id": artifact_id,
            "rights_type": "owner_authorization",
            "source_declaration": "宠物主人授权制作和账户私有分发。",
        },
    )
    assert declared.status_code == 201, declared.text
    right_id = declared.json()["right_id"]
    verified = client.post(
        f"/api/v1/admin/governance/rights/{right_id}/verify",
        headers=reviewer,
        json={"comment": "授权范围与私有分发用途核验通过。"},
    )
    assert verified.status_code == 200, verified.text
    submitted = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/submit-deployment-review",
        headers=editor,
    )
    assert submitted.status_code == 201, submitted.text
    review_id = submitted.json()["review_id"]
    approved = client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{review_id}/approve",
        headers=reviewer,
        json={
            "comment": "版权、视觉身份和兼容性检查通过。",
            "rights_verified": True,
            "visual_identity_verified": True,
        },
    )
    assert approved.status_code == 200, approved.text
    published = client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{review_id}/publish",
        headers=publisher,
        json={"reason": "用于撤销设备回执测试。"},
    )
    assert published.status_code == 201, published.text
    release_id = published.json()["active_release"]["release_id"]
    revoked = client.post(
        f"/api/v1/admin/governance/rights/{right_id}/revoke",
        headers=publisher,
        json={"reason": "授权终止，要求所有设备清理缓存。"},
    )
    assert revoked.status_code == 200, revoked.text
    return {
        "owner_header": owner["Authorization"],
        "publisher_header": publisher["Authorization"],
        "right_id": right_id,
        "artifact_id": artifact_id,
        "release_id": release_id,
        "pet_id": pet_id,
    }


def test_device_acknowledgement_is_scoped_idempotent_and_queryable(
    governance_client: TestClient,
) -> None:
    client = governance_client
    context = _published_revoked_release(client)
    owner_auth = {"Authorization": context["owner_header"]}
    publisher_auth = {"Authorization": context["publisher_header"]}
    device_auth, device_id = _device_auth(client, owner_auth, f"ack-device-{uuid4()}")
    body = {
        "artifact_id": context["artifact_id"],
        "release_id": context["release_id"],
        "pet_id": context["pet_id"],
        "status": "completed",
        "cache_cleared": True,
        "fallback_applied": True,
        "message": "本地精确素材已删除，并切换到内置安全兼容形象。",
        "processed_at": datetime.now(UTC).isoformat(),
    }
    created = client.post(
        f"/api/v1/asset-revocations/{context['right_id']}/acknowledgements",
        headers=device_auth,
        json=body,
    )
    assert created.status_code == 200, created.text
    assert created.json()["attempt_count"] == 1
    assert created.json()["device_id"] == device_id

    repeated = client.post(
        f"/api/v1/asset-revocations/{context['right_id']}/acknowledgements",
        headers=device_auth,
        json={**body, "message": "重复回执按同一设备记录更新。"},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["acknowledgement_id"] == created.json()["acknowledgement_id"]
    assert repeated.json()["attempt_count"] == 2

    mine = client.get(
        "/api/v1/asset-revocations/acknowledgements",
        headers=device_auth,
    )
    assert mine.status_code == 200, mine.text
    assert [item["right_id"] for item in mine.json()] == [context["right_id"]]

    administered = client.get(
        "/api/v1/admin/governance/revocation-acknowledgements",
        headers=publisher_auth,
        params={"right_id": context["right_id"]},
    )
    assert administered.status_code == 200, administered.text
    assert administered.json()[0]["status"] == "completed"


def test_unrelated_device_cannot_acknowledge_another_accounts_pet(
    governance_client: TestClient,
) -> None:
    client = governance_client
    context = _published_revoked_release(client)
    stranger = _register(client, "ack_stranger")
    stranger_device, _ = _device_auth(client, stranger, f"stranger-device-{uuid4()}")
    denied = client.post(
        f"/api/v1/asset-revocations/{context['right_id']}/acknowledgements",
        headers=stranger_device,
        json={
            "artifact_id": context["artifact_id"],
            "release_id": context["release_id"],
            "pet_id": context["pet_id"],
            "status": "completed",
            "cache_cleared": True,
            "fallback_applied": True,
            "message": "不应被接受的跨账户回执。",
            "processed_at": datetime.now(UTC).isoformat(),
        },
    )
    assert denied.status_code == 404, denied.text
