"""Content-governance authorization and personal-release distribution tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from mypets_backend.asset_production_models import (
    PetAssetProductionArtifact,
    PetAssetProductionJob,
)
from mypets_backend.asset_submission_models import UserPetAssetSubmission
from mypets_backend.config import Settings
from mypets_backend.governance_models import PetAssetRight
from mypets_backend.main import create_app
from mypets_backend.models import Account, AdminAuditLog, SyncEvent

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


@pytest.fixture
def governance_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'governance.sqlite3'}",
        jwt_secret="governance-test-secret-more-than-24-chars",
        environment="test",
        admin_usernames=(),
        admin_editor_usernames=("gov_editor", "gov_dual"),
        admin_reviewer_usernames=("gov_reviewer", "gov_dual"),
        admin_publisher_usernames=("gov_publisher",),
        admin_auditor_usernames=("gov_auditor",),
        asset_storage_dir=str(tmp_path / "assets"),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": username,
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_pet(client: TestClient, owner_auth: dict[str, str], template_code: str) -> str:
    response = client.post(
        "/api/v1/pets",
        headers={**owner_auth, "Idempotency-Key": f"governance-pet-{uuid4()}"},
        json={
            "name": "治理测试宠物",
            "template_id": template_code,
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["pet_id"]


def _create_template_version(
    client: TestClient,
    editor_auth: dict[str, str],
    template_code: str,
) -> str:
    created = client.post(
        "/api/v1/admin/pet-templates",
        headers=editor_auth,
        json={
            "template_code": template_code,
            "display_name": "治理测试模板",
            "species": "cat",
            "description": "版权治理与私有发布测试模板。",
        },
    )
    assert created.status_code == 201, created.text
    version = client.post(
        f"/api/v1/admin/pet-templates/{created.json()['id']}/versions",
        headers=editor_auth,
        json={
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert version.status_code == 201, version.text
    return version.json()["id"]


def _package(template_code: str) -> tuple[bytes, dict]:
    manifest = {
        "schema_version": "2.1",
        "template_id": template_code,
        "identity_version": "1.0.0",
        "asset_version": "1.0.0",
        "animations": {action: ["frames/base.png"] for action in _REQUIRED_ACTIONS},
    }
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("frames/base.png", b"governance-test-frame")
    return output.getvalue(), manifest


def _seed_ready_artifact(
    client: TestClient,
    *,
    owner_username: str,
    uploader_username: str,
    pet_id: str,
    template_version_id: str,
    template_code: str,
) -> tuple[str, str]:
    package, manifest = _package(template_code)
    package_sha256 = hashlib.sha256(package).hexdigest()
    submission_id = str(uuid4())
    job_id = str(uuid4())
    artifact_id = str(uuid4())
    object_key = f"production/governance/{job_id}/{artifact_id}/{package_sha256}.zip"
    client.app.state.asset_object_store.write(object_key, package)
    now = datetime.now(UTC)

    with client.app.state.session_factory() as session:
        owner = session.scalar(select(Account).where(Account.username == owner_username))
        uploader = session.scalar(select(Account).where(Account.username == uploader_username))
        assert owner is not None and uploader is not None
        session.add(
            UserPetAssetSubmission(
                id=submission_id,
                account_id=owner.id,
                pet_id=pet_id,
                status="approved",
                style_preference="preserve_original",
                personality_hint="保持稳定识别特征。",
                rights_basis="owner_photo",
                rights_confirmed_at=now,
                original_filename="source.png",
                image_media_type="image/png",
                image_object_key=f"submissions/governance/{submission_id}.png",
                image_sha256=hashlib.sha256(artifact_id.encode()).hexdigest(),
                image_size=128,
                image_width=128,
                image_height=128,
                review_comment="原图权利材料已完成初审。",
                reviewed_by_account_id=uploader.id,
                reviewed_at=now,
            )
        )
        session.flush()
        session.add(
            PetAssetProductionJob(
                id=job_id,
                submission_id=submission_id,
                account_id=owner.id,
                pet_id=pet_id,
                status="ready",
                assignee_account_id=uploader.id,
                progress=100,
                status_note="制作产物已通过声明式素材校验。",
                target_template_version_id=template_version_id,
                started_at=now,
                completed_at=now,
            )
        )
        session.flush()
        session.add(
            PetAssetProductionArtifact(
                id=artifact_id,
                job_id=job_id,
                submission_id=submission_id,
                pet_id=pet_id,
                template_version_id=template_version_id,
                object_key=object_key,
                package_sha256=package_sha256,
                package_size=len(package),
                manifest_json=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                uploaded_by_account_id=uploader.id,
            )
        )
        session.commit()
    return job_id, artifact_id


def _selected_pet_state_version(client: TestClient, owner_auth: dict[str, str], pet_id: str) -> int:
    dashboard = client.get("/api/v1/portal/dashboard", headers=owner_auth)
    assert dashboard.status_code == 200, dashboard.text
    item = next(row for row in dashboard.json()["pets"] if row["pet"]["pet_id"] == pet_id)
    return int(item["pet"]["state_version"])


def test_governance_routes_reject_normal_accounts(governance_client: TestClient) -> None:
    outsider = _register(governance_client, "gov_outsider")
    identity = governance_client.post(
        "/api/v1/admin/governance/identities",
        headers=outsider,
        json={
            "template_id": "blocked-template",
            "identity_version": "v1",
            "features": ["should not be accepted"],
        },
    )
    assert identity.status_code == 403

    rights = governance_client.get("/api/v1/admin/governance/rights", headers=outsider)
    assert rights.status_code == 403


def test_governance_role_separation_and_distribution_shutdown(
    governance_client: TestClient,
) -> None:
    owner = _register(governance_client, "gov_owner")
    editor = _register(governance_client, "gov_editor")
    reviewer = _register(governance_client, "gov_reviewer")
    publisher = _register(governance_client, "gov_publisher")
    dual = _register(governance_client, "gov_dual")
    _register(governance_client, "gov_auditor")

    template_code = "governance.cat.private"
    pet_id = _create_pet(governance_client, owner, template_code)
    template_version_id = _create_template_version(
        governance_client, editor, template_code
    )
    job_id, artifact_id = _seed_ready_artifact(
        governance_client,
        owner_username="gov_owner",
        uploader_username="gov_editor",
        pet_id=pet_id,
        template_version_id=template_version_id,
        template_code=template_code,
    )

    identity = governance_client.post(
        "/api/v1/admin/governance/identities",
        headers=editor,
        json={
            "template_id": template_code,
            "identity_version": "1.0.0",
            "hair_style": "短毛",
            "eye_style": "琥珀色圆眼",
            "color_palette": {"primary": "#f4efe6"},
            "features": ["左耳浅色斑", "尾尖白色"],
            "reference_images": ["submission://approved-source"],
        },
    )
    assert identity.status_code == 200, identity.text
    queried = governance_client.get(
        f"/api/v1/admin/governance/identities/{template_code}",
        headers=reviewer,
    )
    assert queried.status_code == 200, queried.text
    assert queried.json()[0]["features"] == ["左耳浅色斑", "尾尖白色"]

    declared = governance_client.post(
        "/api/v1/admin/governance/rights",
        headers=editor,
        json={
            "artifact_id": artifact_id,
            "rights_type": "owner_authorization",
            "source_declaration": "宠物主人提交原图并授权制作和私有分发。",
        },
    )
    assert declared.status_code == 201, declared.text
    right_id = declared.json()["right_id"]
    assert declared.json()["status"] == "pending"
    assert declared.json()["verified_by_account_id"] is None

    duplicate = governance_client.post(
        "/api/v1/admin/governance/rights",
        headers=editor,
        json={
            "artifact_id": artifact_id,
            "rights_type": "owner_authorization",
            "source_declaration": "重复声明不应被接受。",
        },
    )
    assert duplicate.status_code == 409

    submitted = governance_client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/submit-deployment-review",
        headers=editor,
    )
    assert submitted.status_code == 201, submitted.text
    review_id = submitted.json()["review_id"]

    premature = governance_client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{review_id}/approve",
        headers=reviewer,
        json={
            "comment": "版权尚未独立复核。",
            "rights_verified": True,
            "visual_identity_verified": True,
        },
    )
    assert premature.status_code == 409
    assert "尚未完成独立复核" in premature.text

    editor_cannot_verify = governance_client.post(
        f"/api/v1/admin/governance/rights/{right_id}/verify",
        headers=editor,
        json={"comment": "编辑角色无复核权限。"},
    )
    assert editor_cannot_verify.status_code == 403

    verified = governance_client.post(
        f"/api/v1/admin/governance/rights/{right_id}/verify",
        headers=reviewer,
        json={"comment": "授权链、用途和私有分发范围核验通过。"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"

    approved = governance_client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{review_id}/approve",
        headers=reviewer,
        json={
            "comment": "权利、视觉身份与兼容性全部通过。",
            "rights_verified": True,
            "visual_identity_verified": True,
        },
    )
    assert approved.status_code == 200, approved.text

    published = governance_client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{review_id}/publish",
        headers=publisher,
        json={"reason": "治理链路验证通过并部署。"},
    )
    assert published.status_code == 201, published.text
    download_url = published.json()["active_release"]["download_url"]
    release_id = published.json()["active_release"]["release_id"]
    state_version = _selected_pet_state_version(governance_client, owner, pet_id)

    repeated = governance_client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{review_id}/publish",
        headers=publisher,
        json={"reason": "重复发布请求应按幂等读取处理。"},
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["active_release"]["release_id"] == release_id
    assert _selected_pet_state_version(governance_client, owner, pet_id) == state_version

    before_revoke = governance_client.get(download_url, headers=owner)
    assert before_revoke.status_code == 200, before_revoke.text

    revoked = governance_client.post(
        f"/api/v1/admin/governance/rights/{right_id}/revoke",
        headers=publisher,
        json={"reason": "授权到期，停止服务端分发并要求客户端清理缓存。"},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["right"]["status"] == "revoked"
    assert revoked.json()["affected_release_ids"] == [release_id]

    after_revoke = governance_client.get(download_url, headers=owner)
    assert after_revoke.status_code == 410

    with governance_client.app.state.session_factory() as session:
        right = session.get(PetAssetRight, right_id)
        assert right is not None and right.status == "revoked"
        publish_audits = session.scalar(
            select(func.count(AdminAuditLog.id)).where(
                AdminAuditLog.action == "pet_personal_asset_release.published",
                AdminAuditLog.resource_id == release_id,
            )
        )
        assert publish_audits == 1
        revoke_events = session.scalar(
            select(func.count(SyncEvent.sequence)).where(
                SyncEvent.event_type == "asset_revoked"
            )
        )
        assert revoke_events == 1

    second_job_id, second_artifact_id = _seed_ready_artifact(
        governance_client,
        owner_username="gov_owner",
        uploader_username="gov_editor",
        pet_id=pet_id,
        template_version_id=template_version_id,
        template_code=template_code,
    )
    assert second_job_id
    self_declared = governance_client.post(
        "/api/v1/admin/governance/rights",
        headers=dual,
        json={
            "artifact_id": second_artifact_id,
            "rights_type": "owner_authorization",
            "source_declaration": "双角色账户提交的独立测试声明。",
        },
    )
    assert self_declared.status_code == 201, self_declared.text
    self_verify = governance_client.post(
        f"/api/v1/admin/governance/rights/{self_declared.json()['right_id']}/verify",
        headers=dual,
        json={"comment": "声明人不得自行复核。"},
    )
    assert self_verify.status_code == 409
    assert "不能复核自己的存证" in self_verify.text
