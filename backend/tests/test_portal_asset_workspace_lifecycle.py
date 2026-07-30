from __future__ import annotations

from fastapi.testclient import TestClient


def portal_source(client: TestClient, name: str) -> str:
    response = client.get(f"/portal/{name}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.text


def test_asset_submissions_use_runtime_navigation_and_shared_ui_states(
    client: TestClient,
) -> None:
    source = portal_source(client, "asset-submissions.js")

    assert 'id: "asset-submissions"' in source
    assert "order: 330" in source
    assert 'sectionId === "asset-submissions-section"' in source
    assert "onRefreshComplete: renderAssetPetOptions" in source
    assert "onPetContextRefresh: renderAssetPetOptions" in source
    assert "onRealtime:" in source
    assert "onLogout: resetAssetSubmissionState" in source
    assert 'tab.dataset.section = "asset-submissions-section"' in source
    assert 'tab.addEventListener("click"' not in source
    assert "assetSubmissionUI.renderState" in source
    assert "assetSubmissionUI.renderInlineNotice" in source
    assert "assetSubmissionUI.runAction" in source
    assert "loaded: false" in source
    assert "loading: false" in source
    assert 'error: ""' in source
    assert "Idempotency-Key" in source
    assert "EXIF/GPS" in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source
    assert "setInterval" not in source


def test_asset_production_is_an_independent_lifecycle_feature_without_wrapping(
    client: TestClient,
) -> None:
    source = portal_source(client, "asset-production.js")

    assert 'id: "asset-production"' in source
    assert "order: 340" in source
    assert 'sectionId === "asset-submissions-section"' in source
    assert "onRealtime:" in source
    assert "onLogout: resetAssetProductionState" in source
    assert "assetProductionUI.renderState" in source
    assert "assetProductionUI.renderInlineNotice" in source
    assert "assetProductionUI.runAction" in source
    assert "loaded: false" in source
    assert "loading: false" in source
    assert 'error: ""' in source
    assert "refreshAssetSubmissionWorkspace =" not in source
    assert "refreshAssetSubmissionWorkspaceWithoutProduction" not in source
    assert "13 种动作与安全校验" in source
    assert "Idempotency-Key" in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source
    assert "setInterval" not in source


def test_asset_feature_order_keeps_submission_before_production(
    client: TestClient,
) -> None:
    submission = portal_source(client, "asset-submissions.js")
    production = portal_source(client, "asset-production.js")

    assert "order: 330" in submission
    assert "order: 340" in production
    assert "onSectionEnter:" in submission
    assert "onSectionEnter:" in production
    assert "showLoading: !assetSubmissionState.loaded" in submission
    assert "showLoading: !assetProductionState.loaded" in production
