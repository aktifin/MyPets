from __future__ import annotations

from hashlib import sha256

from fastapi.testclient import TestClient


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


def _create_pet(client: TestClient, auth: dict[str, str], name: str) -> dict:
    suffix = sha256(name.encode("utf-8")).hexdigest()[:20]
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": f"portal-visit-pet-{suffix}"},
        json={
            "name": name,
            "template_id": "official.cat.white",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _friend(
    client: TestClient,
    sender: dict[str, str],
    recipient: dict[str, str],
    recipient_username: str,
) -> None:
    request = client.post(
        "/api/v1/friend-requests",
        headers=sender,
        json={"username": recipient_username},
    )
    assert request.status_code == 201, request.text
    accepted = client.post(
        f"/api/v1/friend-requests/{request.json()['request_id']}/accept",
        headers=recipient,
    )
    assert accepted.status_code == 200, accepted.text


def test_portal_visit_assets_are_same_origin_secure_and_responsive(client: TestClient) -> None:
    page = client.get("/portal")
    assert page.status_code == 200
    assert "异步串门" in page.text
    assert 'id="visits-section"' in page.text
    assert 'src="/portal/visits.js"' in page.text
    assert 'href="/portal/visits.css"' in page.text

    script = client.get("/portal/visits.js")
    assert script.status_code == 200
    assert script.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in script.headers["content-security-policy"]
    assert "/api/v1/visits" in script.text
    assert "/api/v1/friends/" in script.text
    assert "localStorage" not in script.text
    assert "access_token=" not in script.text
    assert "innerHTML" not in script.text

    styles = client.get("/portal/visits.css")
    assert styles.status_code == 200
    assert styles.headers["cache-control"] == "no-store"
    assert "@media (max-width: 560px)" in styles.text
    assert ".visit-pair" in styles.text
    assert ".visit-grid" in styles.text


def test_account_token_portal_visit_flow_exposes_read_only_pair_cards(client: TestClient) -> None:
    visitor_owner = _register(client, "portal_visit_owner", "来访主人")
    host_owner = _register(client, "portal_visit_host", "接待主人")
    visitor_pet = _create_pet(client, visitor_owner, "门户访客")
    host_pet = _create_pet(client, host_owner, "门户接待")
    _friend(client, visitor_owner, host_owner, "portal_visit_host")

    privacy = client.patch(
        f"/api/v1/pets/{host_pet['pet_id']}/privacy",
        headers=host_owner,
        json={"visibility": "friends", "allow_remote_care": False},
    )
    assert privacy.status_code == 200, privacy.text

    host_account = client.get("/api/v1/accounts/me", headers=host_owner)
    assert host_account.status_code == 200, host_account.text
    visible = client.get(
        f"/api/v1/friends/{host_account.json()['id']}/pets",
        headers=visitor_owner,
    )
    assert visible.status_code == 200, visible.text
    assert [item["pet_id"] for item in visible.json()] == [host_pet["pet_id"]]

    created = client.post(
        "/api/v1/visits",
        headers=visitor_owner,
        json={
            "host_username": "portal_visit_host",
            "visitor_pet_id": visitor_pet["pet_id"],
            "host_pet_id": host_pet["pet_id"],
            "duration_minutes": 60,
            "note": "从 Web 门户发起",
        },
    )
    assert created.status_code == 201, created.text
    visit = created.json()
    assert visit["status"] == "pending"
    assert visit["visitor_pet"]["name"] == "门户访客"
    assert visit["host_pet"]["name"] == "门户接待"
    for key in ("presence", "growth_stage", "growth_level", "mood"):
        assert key in visit["visitor_pet"]
        assert key in visit["host_pet"]
    assert "hunger" not in visit["host_pet"]
    assert "health" not in visit["host_pet"]

    incoming = client.get("/api/v1/visits", headers=host_owner)
    assert incoming.status_code == 200, incoming.text
    assert incoming.json()["incoming_requests"][0]["can_accept"] is True

    accepted = client.post(
        f"/api/v1/visits/{visit['visit_id']}/accept",
        headers=host_owner,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "active"
    assert accepted.json()["visitor_pet"]["presence"] == "visiting"

    active = client.get("/api/v1/visits", headers=visitor_owner).json()["active"]
    assert active[0]["can_recall"] is True
    recalled = client.post(
        f"/api/v1/visits/{visit['visit_id']}/recall",
        headers=visitor_owner,
    )
    assert recalled.status_code == 200, recalled.text
    assert recalled.json()["status"] == "recalled"
    assert recalled.json()["visitor_pet"]["presence"] == "home"
