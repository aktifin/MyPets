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
from sqlalchemy import select

from mypets_backend.asset_deployment_models import (
    PetAssetDeploymentReview,
    PetPersonalAssetDeployment,
    PetPersonalAssetRelease,
)
from mypets_backend.asset_production_models import (
    PetAssetProductionArtifact,
    PetAssetProductionJob,
)
from mypets_backend.asset_submission_models import UserPetAssetSubmission
from mypets_backend.config import Settings
from mypets_backend.main import create_app
from mypets_backend.models import Account, Pet, SyncEvent

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
def deployment_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'deployment.sqlite3'}",
        jwt_secret="deployment-test-secret-more-than-24-chars",
        environment="test",
        access_token_minutes=30,
        device_token_hours=12,
        admin_usernames=(),
        admin_editor_usernames=("d3_editor", "d3_dual"),
        admin_reviewer_usernames=("d3_reviewer", "d3_dual"),
        admin_publisher_usernames=("d3_publisher",),
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


def _create_pet(
    client: TestClient,
    owner_auth: dict[str, str],
    *,
    template_code: str,
) -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**owner_auth, "Idempotency-Key": f"d3-pet-{uuid4()}"},
        json={
            "name": "专属素材测试宠物",
            "template_id": template_code,
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_template(
    client: TestClient,
    editor_auth: dict[str, str],
    *,
    template_code: str,
) -> str:
    response = client.post(
        "/api/v1/admin/pet-templates",
        headers=editor_auth,
        json={
            "template_code": template_code,
            "display_name": "专属宠物模板",
            "species": "cat",
            "description": "D3 专属素材部署测试模板。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_version(
    client: TestClient,
    editor_auth: dict[str, str],
    *,
    template_id: str,
    version: str,
) -> str:
    response = client.post(
        f"/api/v1/admin/pet-templates/{template_id}/versions",
        headers=editor_auth,
        json={
            "template_version": version,
            "identity_version": version,
            "asset_version": version,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _package(*, template_code: str, version: str) -> tuple[bytes, dict]:
    manifest = {
        "schema_version": "2.1",
        "template_id": template_code,
        "identity_version": version,
        "asset_version": version,
        "animations": {action: ["frames/base.png"] for action in _REQUIRED_ACTIONS},
    }
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("frames/base.png", b"validated-declarative-test-frame")
    return output.getvalue(), manifest


def _seed_ready_artifact(
    client: TestClient,
    *,
    owner_username: str,
    uploader_username: str,
    pet_id: str,
    template_version_id: str,
    template_code: str,
    version: str,
) -> tuple[str, str, bytes]:
    package, manifest = _package(template_code=template_code, version=version)
    package_sha256 = hashlib.sha256(package).hexdigest()
    submission_id = str(uuid4())
    job_id = str(uuid4())
    artifact_id = str(uuid4())
    object_key = f"production/test/{job_id}/{artifact_id}/{package_sha256}.zip"
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
                personality_hint="保持原角色识别特征。",
                rights_basis="owner_photo",
                rights_confirmed_at=now,
                original_filename=f"source-{version}.png",
                image_media_type="image/png",
                image_object_key=f"submissions/test/{submission_id}.png",
                image_sha256=hashlib.sha256(version.encode()).hexdigest(),
                image_size=128,
                image_width=128,
                image_height=128,
                review_comment="测试中已核验原图权利。",
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
    return job_id, artifact_id, package


def _submit_review(
    client: TestClient,
    *,
    job_id: str,
    editor_auth: dict[str, str],
) -> str:
    response = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/submit-deployment-review",
        headers=editor_auth,
    )
    assert response.status_code == 201, response.text
    return response.json()["review_id"]


def _approve_review(
    client: TestClient,
    *,
    review_id: str,
    reviewer_auth: dict[str, str],
) -> None:
    response = client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{review_id}/approve",
        headers=reviewer_auth,
        json={
            "comment": "权利、视觉身份和兼容性均已独立核验通过。",
            "rights_verified": True,
            "visual_identity_verified": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["compatibility"]["compatible"] is True


def _publish_review(
    client: TestClient,
    *,
    review_id: str,
    publisher_auth: dict[str, str],
    reason: str,
) -> dict:
    response = client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{review_id}/publish",
        headers=publisher_auth,
        json={"reason": reason},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_personal_asset_review_publish_download_and_rollback(
    deployment_client: TestClient,
) -> None:
    client = deployment_client
    owner_auth = _register(client, "d3_owner")
    stranger_auth = _register(client, "d3_stranger")
    editor_auth = _register(client, "d3_editor")
    dual_auth = _register(client, "d3_dual")
    reviewer_auth = _register(client, "d3_reviewer")
    publisher_auth = _register(client, "d3_publisher")

    template_code = "custom.personal.d3"
    pet = _create_pet(client, owner_auth, template_code=template_code)
    pet_id = pet["pet_id"]
    template_id = _create_template(client, editor_auth, template_code=template_code)

    first_version_id = _create_version(
        client, editor_auth, template_id=template_id, version="2.0.0"
    )
    first_job_id, first_artifact_id, first_package = _seed_ready_artifact(
        client,
        owner_username="d3_owner",
        uploader_username="d3_dual",
        pet_id=pet_id,
        template_version_id=first_version_id,
        template_code=template_code,
        version="2.0.0",
    )
    first_review_id = _submit_review(client, job_id=first_job_id, editor_auth=editor_auth)

    repeated = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{first_job_id}/submit-deployment-review",
        headers=dual_auth,
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["review_id"] == first_review_id

    own_review = client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{first_review_id}/approve",
        headers=dual_auth,
        json={
            "comment": "不能审核自己上传的制作产物。",
            "rights_verified": True,
            "visual_identity_verified": True,
        },
    )
    assert own_review.status_code == 409, own_review.text

    incomplete = client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{first_review_id}/approve",
        headers=reviewer_auth,
        json={
            "comment": "视觉身份尚未核验。",
            "rights_verified": True,
            "visual_identity_verified": False,
        },
    )
    assert incomplete.status_code == 422, incomplete.text

    _approve_review(client, review_id=first_review_id, reviewer_auth=reviewer_auth)
    forbidden_publish = client.post(
        f"/api/v1/admin/pet-asset-deployment-reviews/{first_review_id}/publish",
        headers=reviewer_auth,
        json={"reason": "审核员不应具有发布权限。"},
    )
    assert forbidden_publish.status_code == 403, forbidden_publish.text

    first = _publish_review(
        client,
        review_id=first_review_id,
        publisher_auth=publisher_auth,
        reason="D3 首次专属素材部署。",
    )
    first_release = first["active_release"]
    assert first_release["artifact_id"] == first_artifact_id
    assert first_release["asset_version"] == "2.0.0"
    assert first["previous_release"] is None

    mine = client.get(
        f"/api/v1/pets/{pet_id}/personal-asset-deployment", headers=owner_auth
    )
    assert mine.status_code == 200, mine.text
    denied_deployment = client.get(
        f"/api/v1/pets/{pet_id}/personal-asset-deployment", headers=stranger_auth
    )
    assert denied_deployment.status_code == 404

    downloaded = client.get(first_release["download_url"], headers=owner_auth)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == first_package
    assert downloaded.headers["cache-control"].startswith("private")
    denied_package = client.get(first_release["download_url"], headers=stranger_auth)
    assert denied_package.status_code == 404

    second_version_id = _create_version(
        client, editor_auth, template_id=template_id, version="3.0.0"
    )
    second_job_id, _, _ = _seed_ready_artifact(
        client,
        owner_username="d3_owner",
        uploader_username="d3_dual",
        pet_id=pet_id,
        template_version_id=second_version_id,
        template_code=template_code,
        version="3.0.0",
    )
    second_review_id = _submit_review(client, job_id=second_job_id, editor_auth=dual_auth)
    _approve_review(client, review_id=second_review_id, reviewer_auth=reviewer_auth)
    second = _publish_review(
        client,
        review_id=second_review_id,
        publisher_auth=publisher_auth,
        reason="部署 3.0.0 专属素材。",
    )
    first_release_id = first_release["release_id"]
    second_release_id = second["active_release"]["release_id"]
    assert second_release_id != first_release_id
    assert second["previous_release"]["release_id"] == first_release_id
    assert second["active_release"]["asset_version"] == "3.0.0"

    rolled_back = client.post(
        f"/api/v1/admin/pet-personal-asset-deployments/{pet_id}/rollback",
        headers=publisher_auth,
        json={"reason": "3.0.0 客户端验收异常，回退 2.0.0。"},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    rollback = rolled_back.json()
    assert rollback["active_release"]["release_id"] == first_release_id
    assert rollback["previous_release"]["release_id"] == second_release_id
    assert rollback["active_release"]["asset_version"] == "2.0.0"

    with client.app.state.session_factory() as session:
        stored_pet = session.get(Pet, pet_id)
        first_review = session.get(PetAssetDeploymentReview, first_review_id)
        deployment = session.get(PetPersonalAssetDeployment, pet_id)
        assert stored_pet is not None
        assert stored_pet.template_version == "2.0.0"
        assert stored_pet.identity_version == "2.0.0"
        assert stored_pet.asset_version == "2.0.0"
        assert first_review is not None and first_review.status == "published"
        assert deployment is not None and deployment.active_release_id == first_release_id
        releases = list(
            session.scalars(
                select(PetPersonalAssetRelease).where(
                    PetPersonalAssetRelease.pet_id == pet_id
                )
            )
        )
        assert len(releases) == 2
        event_types = list(
            session.scalars(
                select(SyncEvent.event_type).where(
                    SyncEvent.account_id == stored_pet.primary_owner_account_id
                )
            )
        )
        assert "pet_asset_deployment_review_updated" in event_types
        assert "pet_asset_version_changed" in event_types
