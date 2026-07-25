from __future__ import annotations

import json
from io import BytesIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from mypets_backend.asset_production_models import (
    PetAssetProductionArtifact,
    PetAssetProductionJob,
    PetAssetProductionJobLog,
    PetAssetProductionReferenceImage,
)
from mypets_backend.models import Pet, PetAssetRelease, PetTemplateVersion, SyncEvent

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


def _register(client: TestClient, username: str, display_name: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": display_name,
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _pet(
    client: TestClient,
    auth: dict[str, str],
    *,
    name: str,
    template_code: str,
) -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": f"production-pet-{uuid4()}"},
        json={
            "name": name,
            "template_id": template_code,
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _jpeg(*, size: tuple[int, int] = (360, 280), metadata: bool = True) -> bytes:
    image = Image.new("RGB", size, (212, 176, 132))
    output = BytesIO()
    exif = Image.Exif()
    if metadata:
        exif[0x010E] = "private production reference"
        exif[0x0131] = "untrusted tool"
    image.save(output, format="JPEG", quality=91, exif=exif)
    return output.getvalue()


def _submit_and_approve(
    client: TestClient,
    owner_auth: dict[str, str],
    admin_auth: dict[str, str],
    pet_id: str,
    *,
    key: str,
) -> str:
    submitted = client.post(
        "/api/v1/pet-asset-submissions",
        headers={**owner_auth, "Idempotency-Key": key},
        data={
            "pet_id": pet_id,
            "style_preference": "light_chibi",
            "personality_hint": "尾巴末端为白色，性格温柔",
            "rights_basis": "owner_photo",
            "rights_confirmed": "true",
        },
        files={"image": ("source.jpg", _jpeg(), "image/jpeg")},
    )
    assert submitted.status_code == 201, submitted.text
    submission_id = submitted.json()["submission_id"]
    started = client.post(
        f"/api/v1/admin/pet-asset-submissions/{submission_id}/start-review",
        headers=admin_auth,
        json={"comment": "领取并核对原图。"},
    )
    assert started.status_code == 200, started.text
    approved = client.post(
        f"/api/v1/admin/pet-asset-submissions/{submission_id}/approve",
        headers=admin_auth,
        json={"comment": "原图清晰，进入人工制作。"},
    )
    assert approved.status_code == 200, approved.text
    return submission_id


def _template_version(
    client: TestClient,
    admin_auth: dict[str, str],
    *,
    template_code: str,
    identity_version: str = "2.0.0",
    asset_version: str = "2.0.0",
) -> tuple[str, str]:
    template = client.post(
        "/api/v1/admin/pet-templates",
        headers=admin_auth,
        json={
            "template_code": template_code,
            "display_name": "专属形象模板",
            "species": "cat",
            "description": "用户专属素材制作目标。",
        },
    )
    assert template.status_code == 201, template.text
    version = client.post(
        f"/api/v1/admin/pet-templates/{template.json()['id']}/versions",
        headers=admin_auth,
        json={
            "template_version": "2.0.0",
            "identity_version": identity_version,
            "asset_version": asset_version,
        },
    )
    assert version.status_code == 201, version.text
    return template.json()["id"], version.json()["id"]


def _package(
    *,
    template_code: str,
    identity_version: str = "2.0.0",
    asset_version: str = "2.0.0",
) -> bytes:
    frame = BytesIO()
    Image.new("RGBA", (96, 96), (120, 180, 220, 255)).save(frame, format="PNG")
    manifest = {
        "schema_version": "2.1",
        "template_id": template_code,
        "identity_version": identity_version,
        "asset_version": asset_version,
        "animations": {name: ["frames/base.png"] for name in _REQUIRED_ACTIONS},
    }
    archive = BytesIO()
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        bundle.writestr("frames/base.png", frame.getvalue())
    return archive.getvalue()


def test_approved_submission_materializes_one_queued_job_and_user_can_cancel(
    client: TestClient,
) -> None:
    owner_auth = _register(client, "production_owner_cancel", "制作主人")
    stranger_auth = _register(client, "production_stranger", "无权账户")
    admin_auth = _register(client, "admin_creator", "内容管理员")
    pet = _pet(
        client,
        owner_auth,
        name="等待制作小白",
        template_code="custom.production.cancel",
    )
    submission_id = _submit_and_approve(
        client,
        owner_auth,
        admin_auth,
        pet["pet_id"],
        key="production-submit-cancel-001",
    )

    first = client.get("/api/v1/pet-asset-production-jobs", headers=owner_auth)
    assert first.status_code == 200, first.text
    assert len(first.json()) == 1
    job = first.json()[0]
    assert job["submission_id"] == submission_id
    assert job["status"] == "queued"
    assert job["progress"] == 0
    assert job["can_cancel"] is True
    assert job["artifact"] is None
    assert [entry["action"] for entry in job["logs"]] == ["job.created"]

    repeated = client.get("/api/v1/pet-asset-production-jobs", headers=owner_auth)
    assert repeated.status_code == 200
    assert repeated.json()[0]["job_id"] == job["job_id"]

    denied = client.get(
        f"/api/v1/pet-asset-production-jobs/{job['job_id']}", headers=stranger_auth
    )
    assert denied.status_code == 404

    cancelled = client.post(
        f"/api/v1/pet-asset-production-jobs/{job['job_id']}/cancel",
        headers=owner_auth,
        json={"note": "暂时不制作专属形象。"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["can_cancel"] is False

    repeated_cancel = client.post(
        f"/api/v1/pet-asset-production-jobs/{job['job_id']}/cancel",
        headers=owner_auth,
        json={"note": "重复撤回"},
    )
    assert repeated_cancel.status_code == 409

    with client.app.state.session_factory() as session:
        jobs = list(session.scalars(select(PetAssetProductionJob)))
        assert len(jobs) == 1
        assert jobs[0].status == "cancelled"


def test_production_assignment_reference_progress_and_immutable_artifact(
    client: TestClient,
) -> None:
    template_code = "custom.production.ready"
    owner_auth = _register(client, "production_owner_ready", "产物主人")
    stranger_auth = _register(client, "production_other_ready", "其他账户")
    admin_auth = _register(client, "admin_creator", "制作管理员")
    pet = _pet(client, owner_auth, name="专属小蓝", template_code=template_code)
    _template_id, version_id = _template_version(
        client, admin_auth, template_code=template_code
    )
    submission_id = _submit_and_approve(
        client,
        owner_auth,
        admin_auth,
        pet["pet_id"],
        key="production-submit-ready-001",
    )

    queue = client.get(
        "/api/v1/admin/pet-asset-production-jobs?status=queued", headers=admin_auth
    )
    assert queue.status_code == 200, queue.text
    assert len(queue.json()) == 1
    job_id = queue.json()[0]["job_id"]

    assigned = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/assign",
        headers=admin_auth,
        json={
            "assignee_username": "admin_creator",
            "note": "由当前管理员负责动作帧制作。",
        },
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignee_username"] == "admin_creator"

    processing = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/update",
        headers=admin_auth,
        json={"status": "processing", "progress": 20, "note": "已完成主体抠图。"},
    )
    assert processing.status_code == 200, processing.text
    assert processing.json()["status"] == "processing"
    assert processing.json()["progress"] == 20

    regression = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/update",
        headers=admin_auth,
        json={"status": "processing", "progress": 10, "note": "错误回退"},
    )
    assert regression.status_code == 422

    needs_input = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/update",
        headers=admin_auth,
        json={
            "status": "needs_input",
            "progress": 30,
            "note": "需要补充尾巴左侧花纹照片。",
        },
    )
    assert needs_input.status_code == 200, needs_input.text

    reference = client.post(
        f"/api/v1/pet-asset-production-jobs/{job_id}/reference-images",
        headers={**owner_auth, "Idempotency-Key": "production-reference-001"},
        data={"note": "左侧尾巴花纹补充图"},
        files={"image": ("tail.jpg", _jpeg(metadata=True), "image/jpeg")},
    )
    assert reference.status_code == 201, reference.text
    reference_item = reference.json()
    assert reference_item["note"] == "左侧尾巴花纹补充图"

    retry_reference = client.post(
        f"/api/v1/pet-asset-production-jobs/{job_id}/reference-images",
        headers={**owner_auth, "Idempotency-Key": "production-reference-001"},
        data={"note": "不同重试正文"},
        files={"image": ("not-image.jpg", b"retry-body-not-read", "image/jpeg")},
    )
    assert retry_reference.status_code == 201, retry_reference.text
    assert retry_reference.json()["reference_id"] == reference_item["reference_id"]

    downloaded = client.get(reference_item["image_url"], headers=owner_auth)
    assert downloaded.status_code == 200, downloaded.text
    with Image.open(BytesIO(downloaded.content)) as image:
        assert not image.getexif()

    denied_reference = client.get(reference_item["image_url"], headers=stranger_auth)
    assert denied_reference.status_code == 404

    resumed = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/update",
        headers=admin_auth,
        json={"status": "processing", "progress": 60, "note": "补图已确认，继续制作。"},
    )
    assert resumed.status_code == 200, resumed.text

    invalid = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/artifact",
        headers=admin_auth,
        data={"target_template_version_id": version_id},
        files={"package": ("invalid.zip", b"not-a-zip", "application/zip")},
    )
    assert invalid.status_code == 422

    ready = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/artifact",
        headers=admin_auth,
        data={"target_template_version_id": version_id},
        files={
            "package": (
                "production.zip",
                _package(template_code=template_code),
                "application/zip",
            )
        },
    )
    assert ready.status_code == 200, ready.text
    ready_job = ready.json()
    assert ready_job["status"] == "ready"
    assert ready_job["progress"] == 100
    assert ready_job["target_template_version_id"] == version_id
    assert ready_job["artifact"]["target_template_version_id"] == version_id
    assert ready_job["artifact"]["package_url"].startswith("/api/v1/admin/")
    assert ready_job["can_add_reference"] is False

    replace_attempt = client.post(
        f"/api/v1/admin/pet-asset-production-jobs/{job_id}/artifact",
        headers=admin_auth,
        data={"target_template_version_id": version_id},
        files={
            "package": (
                "replacement.zip",
                _package(template_code=template_code),
                "application/zip",
            )
        },
    )
    assert replace_attempt.status_code == 409

    user_job = client.get(
        f"/api/v1/pet-asset-production-jobs/{job_id}", headers=owner_auth
    )
    assert user_job.status_code == 200, user_job.text
    assert user_job.json()["artifact"]["package_url"] is None
    assert user_job.json()["status"] == "ready"

    package = client.get(ready_job["artifact"]["package_url"], headers=admin_auth)
    assert package.status_code == 200
    assert package.headers["content-type"].startswith("application/zip")

    with client.app.state.session_factory() as session:
        stored_pet = session.get(Pet, pet["pet_id"])
        assert stored_pet is not None
        assert stored_pet.identity_version == "1.0.0"
        assert stored_pet.asset_version == "1.0.0"
        version = session.get(PetTemplateVersion, version_id)
        assert version is not None
        assert version.package_sha256 is None
        assert version.staging_object_key is None
        assert session.scalar(select(PetAssetRelease)) is None
        artifact = session.scalar(
            select(PetAssetProductionArtifact).where(
                PetAssetProductionArtifact.job_id == job_id
            )
        )
        assert artifact is not None
        assert artifact.submission_id == submission_id
        assert artifact.pet_id == pet["pet_id"]
        assert session.scalar(
            select(PetAssetProductionReferenceImage).where(
                PetAssetProductionReferenceImage.job_id == job_id
            )
        ) is not None
        actions = list(
            session.scalars(
                select(PetAssetProductionJobLog.action)
                .where(PetAssetProductionJobLog.job_id == job_id)
                .order_by(PetAssetProductionJobLog.created_at)
            )
        )
        assert actions == [
            "job.created",
            "job.assigned",
            "job.status_updated",
            "job.status_updated",
            "reference.added",
            "job.status_updated",
            "artifact.validated",
        ]
        causes = []
        for event in session.scalars(
            select(SyncEvent)
            .where(
                SyncEvent.event_type == "pet_asset_production_job_updated",
                SyncEvent.account_id == ready_job["account_id"],
            )
            .order_by(SyncEvent.sequence)
        ):
            causes.append(json.loads(event.payload_json)["cause"])
        assert causes == [
            "production_job_created",
            "production_job_assigned",
            "production_job_status_updated",
            "production_job_status_updated",
            "production_reference_added",
            "production_job_status_updated",
            "production_artifact_ready",
        ]
