from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import register_account


def test_admin_console_restores_operational_shell_and_governance_assets(
    client: TestClient,
) -> None:
    page = client.get("/admin")
    assert page.status_code == 200
    assert 'id="loginView"' in page.text
    assert 'id="appView"' in page.text
    assert 'id="navigation"' in page.text
    assert 'class="main-content"' in page.text
    assert "/admin/styles.css" in page.text
    assert "/admin/governance-deployment.css" in page.text
    assert "/admin/asset-submissions.js" in page.text
    assert "/admin/asset-production.js" in page.text
    assert "/admin/governance-deployment.js" in page.text
    assert "/admin/rights-evidence.js" in page.text

    governance_script = client.get("/admin/governance-deployment.js")
    evidence_script = client.get("/admin/rights-evidence.js")
    governance_styles = client.get("/admin/governance-deployment.css")
    assert governance_script.status_code == 200
    assert evidence_script.status_code == 200
    assert governance_styles.status_code == 200
    assert "/api/v1/admin/governance/rights" in governance_script.text
    assert "/api/v1/admin/pet-asset-deployment-reviews" in governance_script.text
    assert "/api/v1/admin/pet-personal-asset-deployments" in governance_script.text
    assert "/evidence" in evidence_script.text
    assert "/history" in evidence_script.text
    assert "valid_from" in evidence_script.text
    assert "FormData" in evidence_script.text
    assert "sessionStorage" not in governance_script.text
    assert "sessionStorage" not in evidence_script.text
    assert governance_script.headers["cache-control"] == "no-store"
    assert evidence_script.headers["cache-control"] == "no-store"


def test_administrator_can_list_personal_deployments_and_normal_account_cannot(
    client: TestClient,
) -> None:
    admin = register_account(client, "admin_creator")
    normal = register_account(client, "console_normal_user")

    listed = client.get(
        "/api/v1/admin/pet-personal-asset-deployments",
        headers=admin,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json() == []

    forbidden = client.get(
        "/api/v1/admin/pet-personal-asset-deployments",
        headers=normal,
    )
    assert forbidden.status_code == 403
