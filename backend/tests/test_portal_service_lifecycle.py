from __future__ import annotations

from fastapi.testclient import TestClient


def portal_source(client: TestClient, name: str) -> str:
    response = client.get(f"/portal/{name}")
    assert response.status_code == 200
    return response.text


def test_pending_items_uses_refresh_realtime_logout_and_managed_polling(
    client: TestClient,
) -> None:
    source = portal_source(client, "pending-items-experience.js")

    assert 'id: "pending-items"' in source
    assert "order: 200" in source
    assert "onRefreshComplete:" in source
    assert "onRealtime:" in source
    assert "onLogout:" in source
    assert "startPendingItemsPolling" in source
    assert "stopPendingItemsPolling" in source
    assert "window.clearInterval" in source
    assert 'portalRuntime.requestRefresh({ reason: "pending-action" })' in source
    assert "const baseRefreshAllForPendingItems" not in source
    assert "refreshAll = async function refreshAllWithPendingItems" not in source
    assert 'window.addEventListener("mypets:realtime-cursor"' not in source


def test_customer_history_is_lazy_loaded_by_section_lifecycle(
    client: TestClient,
) -> None:
    source = portal_source(client, "customer-history-experience.js")

    assert 'id: "customer-history"' in source
    assert "order: 300" in source
    assert 'sectionId === "history-section"' in source
    assert "onRealtime:" in source
    assert "onLogout:" in source
    assert 'button.dataset.section = "history-section"' in source
    assert 'button.addEventListener("click", async () =>' not in source
    assert "const baseLogoutForCustomerHistory" not in source
    assert 'window.addEventListener("mypets:realtime-cursor"' not in source


def test_message_efficiency_uses_section_realtime_and_logout_lifecycle(
    client: TestClient,
) -> None:
    source = portal_source(client, "message-efficiency-experience.js")

    assert 'id: "message-efficiency"' in source
    assert "order: 250" in source
    assert 'sectionId === "messages-section"' in source
    assert "refreshMessageEfficiencyView" in source
    assert "resetMessageEfficiencyState" in source
    assert "window.clearTimeout" in source
    assert "onRealtime:" in source
    assert "onLogout:" in source
    assert "const baseLogoutForMessageEfficiency" not in source
    assert 'window.addEventListener("mypets:realtime-cursor"' not in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source


def test_device_self_service_is_lazy_loaded_and_cleared_by_lifecycle(
    client: TestClient,
) -> None:
    source = portal_source(client, "device-self-service.js")

    assert 'id: "device-self-service"' in source
    assert "order: 320" in source
    assert 'sectionId === "account-section"' in source
    assert "onLogout:" in source
    assert "refreshDeviceSelfService" in source
    assert 'document.querySelectorAll(\'[data-section="account-section"]\')' not in source
    assert "access_token" not in source
    assert "device_secret" not in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source


def test_service_lifecycle_order_keeps_pending_before_message_and_lazy_pages(
    client: TestClient,
) -> None:
    pending = portal_source(client, "pending-items-experience.js")
    message = portal_source(client, "message-efficiency-experience.js")
    history = portal_source(client, "customer-history-experience.js")
    devices = portal_source(client, "device-self-service.js")

    assert "order: 200" in pending
    assert "order: 250" in message
    assert "order: 300" in history
    assert "order: 320" in devices
    assert "onRefreshComplete:" not in history
    assert "onRefreshComplete:" not in devices
