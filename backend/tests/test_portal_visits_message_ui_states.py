from __future__ import annotations

from fastapi.testclient import TestClient


def portal_source(client: TestClient, name: str) -> str:
    response = client.get(f"/portal/{name}")
    assert response.status_code == 200
    return response.text


def test_visits_use_shared_loading_error_and_stale_data_states(
    client: TestClient,
) -> None:
    source = portal_source(client, "visits.js")

    assert 'id: "visits"' in source
    assert "order: 350" in source
    assert "const visitUI = window.MyPetsPortalUI" in source
    assert 'loaded: false' in source
    assert 'loading: false' in source
    assert 'error: ""' in source
    assert "friendPetsLoading" in source
    assert "friendPetsError" in source
    assert "renderVisitWorkspaceState" in source
    assert "renderVisitCollectionState" in source
    assert "visitRetryAction" in source
    assert 'kind: "loading"' in source
    assert 'kind: "error"' in source
    assert 'kind: "empty"' in source
    assert "当前仍显示上次成功读取的内容" in source
    assert "visitUI.runAction" in source
    assert 'busyLabel: "正在发送…"' in source
    assert 'busyLabel: "正在刷新…"' in source
    assert 'applyFeatureHook("onVisitsRenderComplete"' in source

    assert 'api("/api/v1/visits")' in source
    assert "/api/v1/friends/" in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source
    assert "setInterval" not in source
    assert "setTimeout" not in source


def test_message_search_separates_new_queries_from_stale_refresh_results(
    client: TestClient,
) -> None:
    source = portal_source(client, "message-efficiency-experience.js")

    assert 'id: "message-efficiency"' in source
    assert "order: 250" in source
    assert "const messageEfficiencyUI = window.MyPetsPortalUI" in source
    assert "searchLoaded" in source
    assert "searchLoading" in source
    assert "searchError" in source
    assert "searchResultQuery" in source
    assert "searchRequestId" in source
    assert "const sameResult = Boolean" in source
    assert "messageEfficiencyState.searchRequestId !== requestId" in source
    assert "messageEfficiencyState.query !== query" in source
    assert "renderMessageSearchStatus" in source
    assert "renderMessageSearchListState" in source
    assert "messageSearchRetryAction" in source
    assert "当前仍显示上次成功搜索的结果" in source
    assert 'kind: "loading"' in source
    assert 'kind: "error"' in source
    assert 'kind: "empty"' in source
    assert 'applyFeatureHook("onFilterConversations"' not in source
    assert "onFilterConversations:" in source
    assert "onConversationsRenderComplete:" in source

    assert "/api/v1/message-search?query=" in source
    assert "/unread-navigation" in source
    assert "/message-window" in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source
    assert "setInterval" not in source


def test_visits_and_message_search_do_not_add_global_entry_wrappers(
    client: TestClient,
) -> None:
    visits = portal_source(client, "visits.js")
    messages = portal_source(client, "message-efficiency-experience.js")

    for source in (visits, messages):
        assert "refreshAll =" not in source
        assert "renderDashboard =" not in source
        assert "renderPortalPhase1 =" not in source
        assert "logout =" not in source
        assert 'window.addEventListener("mypets:realtime-cursor"' not in source
