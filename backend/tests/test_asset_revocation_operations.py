"""End-to-end tests for revoked asset operations aggregation and manual follow-up."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from mypets_backend.asset_revocation_models import PetAssetRevocationFollowUp
from mypets_backend.models import AdminAuditLog

from .test_asset_revocation_acknowledgements import _device_auth, _published_revoked_release
from .test_governance import _register, governance_client


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": "a-strong-test-password"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _failed_acknowledgement_body(context: dict[str, str]) -> dict[str, object]:
    return {
        "artifact_id": context["artifact_id"],
        "release_id": context["release_id"],
        "pet_id": context["pet_id"],
        "status": "failed",
        "cache_cleared": False,
        "fallback_applied": True,
        "message": "缓存目录被占用，等待设备重启后重试。",
        "processed_at": datetime.now(UTC).isoformat(),
    }


def test_revocation_operations_aggregate_failed_and_missing_devices(
    governance_client: TestClient,
) -> None:
    client = governance_client
    context = _published_revoked_release(client)
    owner_auth = {"Authorization": context["owner_header"]}
    publisher_auth = {"Authorization": context["publisher_header"]}
    failed_device_auth, failed_device_id = _device_auth(
        client, owner_auth, f"operations-failed-{uuid4()}"
    )
    _missing_device_auth, missing_device_id = _device_auth(
        client, owner_auth, f"operations-missing-{uuid4()}"
    )

    failed = client.post(
        f"/api/v1/asset-revocations/{context['right_id']}/acknowledgements",
        headers=failed_device_auth,
        json=_failed_acknowledgement_body(context),
    )
    assert failed.status_code == 200, failed.text
    failed_ack_id = failed.json()["acknowledgement_id"]

    dashboard = client.get(
        "/api/v1/admin/governance/revocation-operations",
        headers=publisher_auth,
        params={"right_id": context["right_id"]},
    )
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["totals"] == {
        "revocation_count": 1,
        "expected_device_count": 2,
        "acknowledged_device_count": 1,
        "completed_device_count": 0,
        "failed_device_count": 1,
        "pending_device_count": 1,
        "attention_device_count": 2,
        "investigating_device_count": 0,
        "resolved_device_count": 0,
        "waived_device_count": 0,
    }
    assert payload["groups"][0]["completion_rate"] == 0.0
    rows = {item["device_id"]: item for item in payload["devices"]}
    assert rows[failed_device_id]["acknowledgement_id"] == failed_ack_id
    assert rows[failed_device_id]["acknowledgement_status"] == "failed"
    assert rows[failed_device_id]["needs_attention"] is True
    assert rows[missing_device_id]["acknowledgement_id"] is None
    assert rows[missing_device_id]["needs_attention"] is True

    investigating = client.post(
        "/api/v1/admin/governance/revocation-follow-ups",
        headers=publisher_auth,
        json={
            "right_id": context["right_id"],
            "release_id": context["release_id"],
            "device_id": failed_device_id,
            "status": "investigating",
            "note": "已联系用户，安排关闭占用进程后重新同步。",
        },
    )
    assert investigating.status_code == 201, investigating.text
    assert investigating.json()["acknowledgement_id"] == failed_ack_id

    waived = client.post(
        "/api/v1/admin/governance/revocation-follow-ups",
        headers=publisher_auth,
        json={
            "right_id": context["right_id"],
            "release_id": context["release_id"],
            "device_id": missing_device_id,
            "status": "waived",
            "note": "用户确认该设备已报废且磁盘已经销毁，豁免继续回执。",
        },
    )
    assert waived.status_code == 201, waived.text
    assert waived.json()["acknowledgement_id"] is None

    attention = client.get(
        "/api/v1/admin/governance/revocation-operations",
        headers=publisher_auth,
        params={"right_id": context["right_id"], "attention_only": "true"},
    )
    assert attention.status_code == 200, attention.text
    attention_payload = attention.json()
    assert attention_payload["totals"]["attention_device_count"] == 1
    assert attention_payload["totals"]["investigating_device_count"] == 1
    assert attention_payload["totals"]["waived_device_count"] == 1
    assert [item["device_id"] for item in attention_payload["devices"]] == [failed_device_id]

    resolved = client.post(
        "/api/v1/admin/governance/revocation-follow-ups",
        headers=publisher_auth,
        json={
            "right_id": context["right_id"],
            "release_id": context["release_id"],
            "device_id": failed_device_id,
            "status": "resolved",
            "note": "设备重新上线后确认缓存已清理，人工复核完成。",
        },
    )
    assert resolved.status_code == 201, resolved.text

    history = client.get(
        "/api/v1/admin/governance/revocation-follow-ups",
        headers=publisher_auth,
        params={
            "right_id": context["right_id"],
            "release_id": context["release_id"],
            "device_id": failed_device_id,
        },
    )
    assert history.status_code == 200, history.text
    assert [item["status"] for item in history.json()] == ["resolved", "investigating"]

    closed = client.get(
        "/api/v1/admin/governance/revocation-operations",
        headers=publisher_auth,
        params={"right_id": context["right_id"], "attention_only": "true"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["totals"]["attention_device_count"] == 0
    assert closed.json()["devices"] == []

    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count(PetAssetRevocationFollowUp.id))) == 3
        audit_count = session.scalar(
            select(func.count(AdminAuditLog.id)).where(
                AdminAuditLog.action == "pet_asset_revocation.follow_up_recorded"
            )
        )
        assert audit_count == 3


def test_only_publishers_can_record_revocation_follow_up(
    governance_client: TestClient,
) -> None:
    client = governance_client
    context = _published_revoked_release(client)
    owner_auth = {"Authorization": context["owner_header"]}
    _device_auth_header, device_id = _device_auth(
        client, owner_auth, f"operations-permission-{uuid4()}"
    )
    editor_auth = _login(client, "gov_editor")
    normal_auth = _register(client, "operations_normal")
    body = {
        "right_id": context["right_id"],
        "release_id": context["release_id"],
        "device_id": device_id,
        "status": "investigating",
        "note": "权限边界测试记录。",
    }

    editor_denied = client.post(
        "/api/v1/admin/governance/revocation-follow-ups",
        headers=editor_auth,
        json=body,
    )
    assert editor_denied.status_code == 403, editor_denied.text
    assert editor_denied.json()["required_permission"] == "publish"

    normal_denied = client.post(
        "/api/v1/admin/governance/revocation-follow-ups",
        headers=normal_auth,
        json=body,
    )
    assert normal_denied.status_code == 403, normal_denied.text
