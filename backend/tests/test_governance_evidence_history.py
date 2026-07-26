"""End-to-end tests for rights evidence, validity windows, and review history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from .test_governance import (
    _create_pet,
    _create_template_version,
    _register,
    _seed_ready_artifact,
    governance_client,
)


def _declare(
    client: TestClient,
    editor: dict[str, str],
    artifact_id: str,
    *,
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> dict:
    response = client.post(
        "/api/v1/admin/governance/rights",
        headers=editor,
        json={
            "artifact_id": artifact_id,
            "rights_type": "owner_authorization",
            "source_declaration": "宠物主人授权制作并在账户范围内私有分发。",
            "valid_from": valid_from.isoformat() if valid_from else None,
            "valid_until": valid_until.isoformat() if valid_until else None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_rights_evidence_terms_review_and_history(governance_client: TestClient) -> None:
    client = governance_client
    owner = _register(client, "evidence_owner")
    editor = _register(client, "gov_editor")
    reviewer = _register(client, "gov_reviewer")
    _register(client, "gov_publisher")

    template_code = "governance.cat.evidence"
    pet_id = _create_pet(client, owner, template_code)
    template_version_id = _create_template_version(client, editor, template_code)
    _job_id, artifact_id = _seed_ready_artifact(
        client,
        owner_username="evidence_owner",
        uploader_username="gov_editor",
        pet_id=pet_id,
        template_version_id=template_version_id,
        template_code=template_code,
    )
    now = datetime.now(UTC)
    declared = _declare(
        client,
        editor,
        artifact_id,
        valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(days=30),
    )
    right_id = declared["right_id"]
    assert declared["status"] == "pending"
    assert declared["validity_state"] == "active"
    assert declared["evidence_count"] == 1  # approved source submission is linked automatically

    reviewer_upload = client.post(
        f"/api/v1/admin/governance/rights/{right_id}/evidence",
        headers=reviewer,
        files={"evidence": ("blocked.pdf", b"%PDF-blocked", "application/pdf")},
    )
    assert reviewer_upload.status_code == 403

    evidence_body = b"%PDF-1.4\nrights authorization evidence\n%%EOF"
    uploaded = client.post(
        f"/api/v1/admin/governance/rights/{right_id}/evidence",
        headers=editor,
        files={"evidence": ("authorization.pdf", evidence_body, "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    evidence = uploaded.json()
    assert evidence["original_filename"] == "authorization.pdf"
    assert evidence["size_bytes"] == len(evidence_body)

    duplicate = client.post(
        f"/api/v1/admin/governance/rights/{right_id}/evidence",
        headers=editor,
        files={"evidence": ("renamed.pdf", evidence_body, "application/pdf")},
    )
    assert duplicate.status_code == 409

    listed = client.get(
        f"/api/v1/admin/governance/rights/{right_id}/evidence",
        headers=reviewer,
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 2
    uploaded_row = next(
        item for item in listed.json() if item["original_filename"] == "authorization.pdf"
    )
    downloaded = client.get(uploaded_row["download_url"], headers=reviewer)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == evidence_body
    assert downloaded.headers["cache-control"] == "private, no-store"

    extended_until = now + timedelta(days=60)
    terms = client.post(
        f"/api/v1/admin/governance/rights/{right_id}/terms",
        headers=editor,
        json={
            "valid_from": (now - timedelta(hours=2)).isoformat(),
            "valid_until": extended_until.isoformat(),
        },
    )
    assert terms.status_code == 200, terms.text
    assert terms.json()["validity_state"] == "active"

    invalid_terms = client.post(
        f"/api/v1/admin/governance/rights/{right_id}/terms",
        headers=editor,
        json={
            "valid_from": (now + timedelta(days=2)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
        },
    )
    assert invalid_terms.status_code == 422

    verified = client.post(
        f"/api/v1/admin/governance/rights/{right_id}/verify",
        headers=reviewer,
        json={"comment": "授权主体、使用范围、有效期与附件证据均核验通过。"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"
    assert verified.json()["review_comment"].startswith("授权主体")
    assert verified.json()["verified_at"] is not None
    assert verified.json()["evidence_count"] == 2

    locked_terms = client.post(
        f"/api/v1/admin/governance/rights/{right_id}/terms",
        headers=editor,
        json={"valid_from": None, "valid_until": None},
    )
    assert locked_terms.status_code == 409

    history = client.get(
        f"/api/v1/admin/governance/rights/{right_id}/history",
        headers=reviewer,
    )
    assert history.status_code == 200, history.text
    event_types = [item["event_type"] for item in history.json()]
    assert event_types == [
        "declared",
        "source_evidence_linked",
        "evidence_added",
        "terms_updated",
        "verified",
    ]
    assert history.json()[-1]["comment"].startswith("授权主体")


def test_scheduled_and_expired_rights_block_governed_approval(
    governance_client: TestClient,
) -> None:
    client = governance_client
    owner = _register(client, "validity_owner")
    editor = _register(client, "gov_editor")
    reviewer = _register(client, "gov_reviewer")

    template_code = "governance.cat.validity"
    pet_id = _create_pet(client, owner, template_code)
    template_version_id = _create_template_version(client, editor, template_code)
    job_id, artifact_id = _seed_ready_artifact(
        client,
        owner_username="validity_owner",
        uploader_username="gov_editor",
        pet_id=pet_id,
        template_version_id=template_version_id,
        template_code=template_code,
    )
    now = datetime.now(UTC)
    scheduled = _declare(
        client,
        editor,
        artifact_id,
        valid_from=now + timedelta(days=1),
        valid_until=now + timedelta(days=30),
    )
    verified = client.post(
        f"/api/v1/admin/governance/rights/{scheduled['right_id']}/verify",
        headers=reviewer,
        json={"comment": "证据有效，但授权将在未来生效。"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["validity_state"] == "scheduled"

    review = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/submit-deployment-review",
        headers=editor,
    )
    assert review.status_code == 201, review.text
    approval = client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{review.json()['review_id']}/approve",
        headers=reviewer,
        json={
            "comment": "未来授权不能提前批准部署。",
            "rights_verified": True,
            "visual_identity_verified": True,
        },
    )
    assert approval.status_code == 409
    assert "尚未到生效时间" in approval.text

    second_job_id, second_artifact_id = _seed_ready_artifact(
        client,
        owner_username="validity_owner",
        uploader_username="gov_editor",
        pet_id=pet_id,
        template_version_id=template_version_id,
        template_code=template_code,
    )
    assert second_job_id
    expired = _declare(
        client,
        editor,
        second_artifact_id,
        valid_from=now - timedelta(days=30),
        valid_until=now - timedelta(days=1),
    )
    expired_verify = client.post(
        f"/api/v1/admin/governance/rights/{expired['right_id']}/verify",
        headers=reviewer,
        json={"comment": "已经过期的授权不能核验为有效。"},
    )
    assert expired_verify.status_code == 409
    assert "有效期已经结束" in expired_verify.text
