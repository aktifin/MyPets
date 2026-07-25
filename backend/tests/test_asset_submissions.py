from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from mypets_backend.asset_submission_models import UserPetAssetSubmission
from mypets_backend.models import Pet, SyncEvent


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


def _create_pet(client: TestClient, auth: dict[str, str], name: str = "原型小白") -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": f"asset-pet-{uuid4()}"},
        json={
            "name": name,
            "template_id": "official.onepic.demo",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _jpeg_bytes(*, size: tuple[int, int] = (320, 240), exif: bool = True) -> bytes:
    image = Image.new("RGB", size, (230, 190, 140))
    output = BytesIO()
    metadata = Image.Exif()
    if exif:
        metadata[0x010E] = "private original metadata"
        metadata[0x0131] = "untrusted-uploader"
    image.save(output, format="JPEG", quality=91, exif=metadata)
    return output.getvalue()


def _submit(
    client: TestClient,
    auth: dict[str, str],
    pet_id: str,
    *,
    key: str,
    image_bytes: bytes | None = None,
    media_type: str = "image/jpeg",
    filename: str = "my-cat.jpg",
    rights_confirmed: str = "true",
) -> object:
    return client.post(
        "/api/v1/pet-asset-submissions",
        headers={**auth, "Idempotency-Key": key},
        data={
            "pet_id": pet_id,
            "style_preference": "light_chibi",
            "personality_hint": "温柔、喜欢趴在窗边",
            "rights_basis": "owner_photo",
            "rights_confirmed": rights_confirmed,
        },
        files={
            "image": (
                filename,
                image_bytes if image_bytes is not None else _jpeg_bytes(),
                media_type,
            )
        },
    )


def test_user_upload_is_sanitized_idempotent_and_private(client: TestClient) -> None:
    owner_auth = _register(client, "asset_owner", "形象主人")
    stranger_auth = _register(client, "asset_stranger", "其他用户")
    pet = _create_pet(client, owner_auth)
    source = _jpeg_bytes(exif=True)

    created = _submit(
        client,
        owner_auth,
        pet["pet_id"],
        key="asset-submission-create-001",
        image_bytes=source,
        filename="folder\\private-cat.jpg",
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["status"] == "pending_processing"
    assert item["style_preference"] == "light_chibi"
    assert item["publication_ready"] is False
    assert item["original_filename"] == "private-cat.jpg"
    assert item["image_media_type"] == "image/jpeg"
    assert item["image_width"] == 320
    assert item["image_height"] == 240
    assert item["image_sha256"]

    retried = _submit(
        client,
        owner_auth,
        pet["pet_id"],
        key="asset-submission-create-001",
        image_bytes=b"not-the-original-request-anymore",
        media_type="image/jpeg",
    )
    assert retried.status_code == 201, retried.text
    assert retried.json()["submission_id"] == item["submission_id"]

    duplicate = _submit(
        client,
        owner_auth,
        pet["pet_id"],
        key="asset-submission-create-duplicate",
        image_bytes=source,
    )
    assert duplicate.status_code == 409

    downloaded = client.get(item["image_url"], headers=owner_auth)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"].startswith("image/jpeg")
    with Image.open(BytesIO(downloaded.content)) as image:
        assert image.size == (320, 240)
        assert not image.getexif()

    denied = client.get(item["image_url"], headers=stranger_auth)
    assert denied.status_code == 404
    admin_denied = client.get("/api/v1/admin/pet-asset-submissions", headers=owner_auth)
    assert admin_denied.status_code == 403


def test_submission_validation_and_pet_permissions(client: TestClient) -> None:
    owner_auth = _register(client, "asset_validation_owner", "校验主人")
    other_auth = _register(client, "asset_validation_other", "无权用户")
    pet = _create_pet(client, owner_auth)

    missing_rights = _submit(
        client,
        owner_auth,
        pet["pet_id"],
        key="asset-validation-rights",
        rights_confirmed="false",
    )
    assert missing_rights.status_code == 422
    assert "权利" in missing_rights.text

    fake_png = _submit(
        client,
        owner_auth,
        pet["pet_id"],
        key="asset-validation-fake-image",
        image_bytes=b"<svg><script>alert(1)</script></svg>",
        media_type="image/png",
        filename="unsafe.png",
    )
    assert fake_png.status_code == 422

    too_small = _submit(
        client,
        owner_auth,
        pet["pet_id"],
        key="asset-validation-small-image",
        image_bytes=_jpeg_bytes(size=(32, 32), exif=False),
    )
    assert too_small.status_code == 422
    assert "64" in too_small.text

    foreign_pet = _submit(
        client,
        other_auth,
        pet["pet_id"],
        key="asset-validation-foreign-pet",
    )
    assert foreign_pet.status_code == 404


def test_admin_review_state_machine_preserves_pet_versions_and_emits_audit(
    client: TestClient,
) -> None:
    owner_auth = _register(client, "asset_review_owner", "审核对象主人")
    admin_auth = _register(client, "admin_creator", "内容管理员")
    pet = _create_pet(client, owner_auth, "待制作小白")
    created = _submit(
        client,
        owner_auth,
        pet["pet_id"],
        key="asset-review-create-001",
    )
    assert created.status_code == 201, created.text
    submission_id = created.json()["submission_id"]

    queue = client.get(
        "/api/v1/admin/pet-asset-submissions?status=pending_processing",
        headers=admin_auth,
    )
    assert queue.status_code == 200, queue.text
    assert [item["submission_id"] for item in queue.json()] == [submission_id]
    assert queue.json()[0]["image_url"].startswith("/api/v1/admin/")

    image = client.get(queue.json()[0]["image_url"], headers=admin_auth)
    assert image.status_code == 200

    started = client.post(
        f"/api/v1/admin/pet-asset-submissions/{submission_id}/start-review",
        headers=admin_auth,
        json={"comment": "已领取，检查主体轮廓。"},
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_review"

    cannot_start_twice = client.post(
        f"/api/v1/admin/pet-asset-submissions/{submission_id}/start-review",
        headers=admin_auth,
        json={"comment": "重复领取"},
    )
    assert cannot_start_twice.status_code == 409

    approved = client.post(
        f"/api/v1/admin/pet-asset-submissions/{submission_id}/approve",
        headers=admin_auth,
        json={"comment": "主体清晰，进入人工动作帧制作队列。"},
    )
    assert approved.status_code == 200, approved.text
    approved_item = approved.json()
    assert approved_item["status"] == "approved"
    assert approved_item["publication_ready"] is False
    assert approved_item["reviewed_at"]

    user_view = client.get(
        f"/api/v1/pet-asset-submissions/{submission_id}", headers=owner_auth
    )
    assert user_view.status_code == 200
    assert user_view.json()["status"] == "approved"
    assert "人工动作帧" in user_view.json()["review_comment"]

    with client.app.state.session_factory() as session:
        stored_pet = session.get(Pet, pet["pet_id"])
        assert stored_pet is not None
        assert stored_pet.identity_version == "1.0.0"
        assert stored_pet.asset_version == "1.0.0"
        stored_submission = session.get(UserPetAssetSubmission, submission_id)
        assert stored_submission is not None
        assert stored_submission.status == "approved"
        causes = []
        for event in session.scalars(
            select(SyncEvent)
            .where(
                SyncEvent.account_id == stored_submission.account_id,
                SyncEvent.event_type == "pet_asset_submission_updated",
            )
            .order_by(SyncEvent.sequence)
        ):
            causes.append(__import__("json").loads(event.payload_json)["cause"])
        assert causes == [
            "submission_created",
            "submission_review_started",
            "submission_approved",
        ]

    audits = client.get("/api/v1/admin/audit-logs?limit=50", headers=admin_auth)
    assert audits.status_code == 200, audits.text
    actions = [item["action"] for item in audits.json()]
    assert "pet_asset_submission.start-review" in actions
    assert "pet_asset_submission.approve" in actions


def test_rejection_requires_reason_and_is_visible_to_owner(client: TestClient) -> None:
    owner_auth = _register(client, "asset_reject_owner", "驳回主人")
    admin_auth = _register(client, "admin_reviewer", "审核管理员")
    pet = _create_pet(client, owner_auth)
    created = _submit(
        client,
        owner_auth,
        pet["pet_id"],
        key="asset-reject-create-001",
        image_bytes=_jpeg_bytes(size=(400, 300)),
    )
    submission_id = created.json()["submission_id"]
    started = client.post(
        f"/api/v1/admin/pet-asset-submissions/{submission_id}/start-review",
        headers=admin_auth,
        json={"comment": ""},
    )
    assert started.status_code == 200

    missing_reason = client.post(
        f"/api/v1/admin/pet-asset-submissions/{submission_id}/reject",
        headers=admin_auth,
        json={"comment": "否"},
    )
    assert missing_reason.status_code == 422

    rejected = client.post(
        f"/api/v1/admin/pet-asset-submissions/{submission_id}/reject",
        headers=admin_auth,
        json={"comment": "主体被遮挡，请上传正面且光线清晰的照片。"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    owner_list = client.get(
        "/api/v1/pet-asset-submissions?status=rejected", headers=owner_auth
    )
    assert owner_list.status_code == 200
    assert owner_list.json()[0]["submission_id"] == submission_id
    assert "主体被遮挡" in owner_list.json()[0]["review_comment"]
