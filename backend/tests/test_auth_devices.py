from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from mypets_backend.models import Account, Device

from .conftest import bind_device


def test_register_login_and_current_account(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "username": "Alice.User",
            "display_name": "Alice",
            "password": "correct-horse-battery-staple",
        },
    )
    assert registration.status_code == 201
    assert registration.json()["account"]["username"] == "alice.user"

    duplicate = client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice.user",
            "display_name": "Another",
            "password": "another-long-password",
        },
    )
    assert duplicate.status_code == 409

    wrong = client.post(
        "/api/v1/auth/token",
        data={"username": "alice.user", "password": "wrong-password"},
    )
    assert wrong.status_code == 401

    login = client.post(
        "/api/v1/auth/token",
        data={
            "username": "Alice.User",
            "password": "correct-horse-battery-staple",
        },
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    current = client.get("/api/v1/accounts/me", headers=headers)
    assert current.status_code == 200
    assert current.json()["display_name"] == "Alice"

    with client.app.state.session_factory() as session:
        account = session.scalar(select(Account).where(Account.username == "alice.user"))
        assert account is not None
        assert account.password_hash != "correct-horse-battery-staple"
        assert account.password_hash.startswith("$argon2")


def test_device_binding_secret_exchange_and_revocation(
    client: TestClient, account_auth: dict[str, str]
) -> None:
    device, device_auth, raw_secret = bind_device(client, account_auth)
    assert len(raw_secret) >= 32

    listed = client.get("/api/v1/devices", headers=account_auth)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == device["id"]
    assert "device_secret" not in listed.json()[0]

    bootstrap = client.get("/api/v1/sync/bootstrap", headers=device_auth)
    assert bootstrap.status_code == 200
    assert bootstrap.json()["device"]["id"] == device["id"]

    with client.app.state.session_factory() as session:
        stored = session.get(Device, device["id"])
        assert stored is not None
        assert stored.secret_hash != raw_secret
        assert len(stored.secret_hash) == 64

    revoked = client.delete(f"/api/v1/devices/{device['id']}", headers=account_auth)
    assert revoked.status_code == 204
    assert client.get("/api/v1/sync/bootstrap", headers=device_auth).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/device-token",
            json={"device_id": device["id"], "device_secret": raw_secret},
        ).status_code
        == 401
    )


def test_rebinding_rotates_device_secret(
    client: TestClient, account_auth: dict[str, str]
) -> None:
    device, first_auth, first_secret = bind_device(client, account_auth)
    second, second_auth, second_secret = bind_device(client, account_auth)
    assert second["id"] == device["id"]
    assert second_secret != first_secret

    assert client.get("/api/v1/sync/bootstrap", headers=first_auth).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/device-token",
            json={"device_id": device["id"], "device_secret": first_secret},
        ).status_code
        == 401
    )
    assert client.get("/api/v1/sync/bootstrap", headers=second_auth).status_code == 200
