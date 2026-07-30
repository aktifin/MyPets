from __future__ import annotations

from fastapi.testclient import TestClient


def test_party_pending_web_extension_is_loaded_after_party_scene(client: TestClient) -> None:
    response = client.get("/portal")

    assert response.status_code == 200
    party_index = response.text.index('/portal/party-experience.js')
    pending_index = response.text.index('/portal/party-pending-experience.js')
    assert party_index < pending_index
    assert response.headers["cache-control"] == "no-store"


def test_party_pending_web_extension_keeps_navigation_read_only(client: TestClient) -> None:
    response = client.get("/portal/party-pending-experience.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert 'pendingKindLabels.party_invitation = "宠物聚会"' in response.text
    assert 'id: "party-pending"' in response.text
    assert 'kind: "party"' in response.text
    assert "id: context.item.item_id" in response.text
    assert 'button.textContent = "进入聚会"' in response.text
    assert 'context.kind !== "party"' in response.text
    assert "openPartyDetail(context.targetId)" in response.text
    assert "refreshPendingItems()" in response.text
    assert "basePendingTargetForParties" not in response.text
    assert "baseActivateCustomerTargetForParties" not in response.text
    assert "window.open" not in response.text
    assert "new Worker" not in response.text
    assert "WebSocket" not in response.text
    assert "/api/v1/pending-items/party_invitation" not in response.text
