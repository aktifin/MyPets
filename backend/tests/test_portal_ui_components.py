from __future__ import annotations

from fastapi.testclient import TestClient


def portal_source(client: TestClient, name: str) -> str:
    response = client.get(f"/portal/{name}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    return response.text


def test_shared_ui_assets_load_before_feature_extensions(client: TestClient) -> None:
    page = client.get("/portal")

    assert page.status_code == 200
    assert '/portal/portal-ui.css' in page.text
    assert '/portal/portal-ui.js' in page.text
    phase1_index = page.text.index('/portal/phase1.js')
    ui_index = page.text.index('/portal/portal-ui.js')
    realtime_index = page.text.index('/portal/realtime.js')
    pending_index = page.text.index('/portal/pending-items-experience.js')
    bootstrap_index = page.text.index('/portal/portal-bootstrap.js')
    assert phase1_index < ui_index < realtime_index < pending_index < bootstrap_index

    portal_source(client, "portal-ui.js")
    css = portal_source(client, "portal-ui.css")
    assert ".portal-ui-state" in css
    assert ".portal-ui-state-error" in css
    assert "[data-portal-ui-busy=\"1\"]" in css


def test_shared_ui_owns_accessible_state_and_action_feedback(client: TestClient) -> None:
    source = portal_source(client, "portal-ui.js")

    assert "function renderState" in source
    assert "function renderInlineNotice" in source
    assert "function runAction" in source
    assert "function setRegionBusy" in source
    assert 'state.setAttribute("role", kind === "error" ? "alert" : "status")' in source
    assert 'control.setAttribute("aria-busy", "true")' in source
    assert 'window.MyPetsPortalUI = api' in source
    assert 'window.empty = renderEmpty' in source
    assert 'window.actionButton = sharedActionButton' in source
    assert "fetch(" not in source
    assert "api(" not in source
    assert "WebSocket" not in source
    assert "new Worker" not in source
    assert "setInterval" not in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source


def test_home_lists_use_the_shared_empty_and_action_entry_points(client: TestClient) -> None:
    phase1 = portal_source(client, "phase1.js")
    ui = portal_source(client, "portal-ui.js")

    assert 'empty(growthList, "暂无成长变化' in phase1
    assert 'empty(activityList, "暂无互动履历' in phase1
    assert 'empty(container, "当前分类暂无会话' in phase1
    assert 'empty(container, "暂无提醒' in phase1
    assert 'actionButton("查看", () => openConversation(conversation))' in phase1
    assert 'window.empty = renderEmpty' in ui
    assert 'window.actionButton = sharedActionButton' in ui


def test_pending_items_preserve_stale_data_and_show_unified_states(
    client: TestClient,
) -> None:
    source = portal_source(client, "pending-items-experience.js")

    assert "const pendingItemsUI = window.MyPetsPortalUI" in source
    assert "loaded: false" in source
    assert "loading: false" in source
    assert 'error: ""' in source
    assert 'kind: "loading"' in source
    assert 'kind: "empty"' in source
    assert 'kind: "error"' in source
    assert "renderInlineNotice" in source
    assert "runAction" in source
    assert 'refreshPendingItems({ showLoading: false }).catch(() => {})' in source
    assert 'title: "最新状态暂未更新"' in source
    assert "empty(list" not in source


def test_history_uses_idle_loading_empty_error_and_retry_states(
    client: TestClient,
) -> None:
    source = portal_source(client, "customer-history-experience.js")

    assert "const customerHistoryUI = window.MyPetsPortalUI" in source
    assert 'kind: "idle"' in source
    assert 'kind: "loading"' in source
    assert 'kind: "empty"' in source
    assert 'kind: "error"' in source
    assert "renderInlineNotice" in source
    assert 'busyLabel: "正在刷新…"' in source
    assert 'busyLabel: "正在打开…"' in source
    assert 'refreshCustomerHistory({ showLoading: false })' in source
    assert 'className = "empty-state"' not in source


def test_device_self_service_uses_local_feedback_and_privacy_boundaries(
    client: TestClient,
) -> None:
    source = portal_source(client, "device-self-service.js")

    assert "const deviceSelfServiceUI = window.MyPetsPortalUI" in source
    assert 'kind: "idle"' in source
    assert 'kind: "loading"' in source
    assert 'kind: "empty"' in source
    assert 'kind: "error"' in source
    assert 'busyLabel: "正在撤销…"' in source
    assert 'busyLabel: "正在生成…"' in source
    assert "renderInlineNotice" in source
    assert "password" not in source.lower()
    assert "access_token" not in source
    assert "device_key" not in source
    assert "不包含密码、访问令牌、设备密钥" in source
