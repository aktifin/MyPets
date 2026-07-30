from __future__ import annotations

from fastapi.testclient import TestClient


def portal_source(client: TestClient, name: str) -> str:
    response = client.get(f"/portal/{name}")
    assert response.status_code == 200
    return response.text


def test_runtime_supports_sync_async_and_queued_feature_projections(
    client: TestClient,
) -> None:
    source = portal_source(client, "portal-runtime.js")

    assert "function applyFeatureHook" in source
    assert "function queueFeatureHook" in source
    assert "function invokeFeatureSync" in source
    assert "hookPromises: new Map()" in source
    assert "applyFeatureHook," in source
    assert "queueFeatureHook," in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source


def test_phase1_publishes_message_and_reminder_projection_hooks(
    client: TestClient,
) -> None:
    source = portal_source(client, "phase1.js")

    assert 'applyFeatureHook("onFilterConversations"' in source
    assert 'applyFeatureHook("onConversationsRenderComplete"' in source
    assert 'applyFeatureHook("onConversationOpenRequest"' in source
    assert 'runFeatureHook("onConversationOpenComplete"' in source
    assert 'applyFeatureHook("onRemindersRenderComplete"' in source
    assert 'applyFeatureHook("onPhase1RenderComplete"' in source
    assert "async function openConversation(conversation, options = {})" in source


def test_message_efficiency_no_longer_replaces_shared_message_functions(
    client: TestClient,
) -> None:
    source = portal_source(client, "message-efficiency-experience.js")

    assert 'id: "message-efficiency"' in source
    assert "order: 250" in source
    assert "onFilterConversations:" in source
    assert "onConversationsRenderComplete:" in source
    assert "onConversationOpenRequest:" in source
    assert "onMessageActionsRenderComplete:" in source
    assert "filteredConversations = function" not in source
    assert "renderConversations = function" not in source
    assert "openConversation = async function" not in source
    assert "sendCustomerConversationMessage = async function" not in source
    assert "renderMessageActions = function" not in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source


def test_customer_actions_uses_projection_hooks_without_global_wrappers(
    client: TestClient,
) -> None:
    source = portal_source(client, "customer-actions-experience.js")

    assert 'id: "customer-actions"' in source
    assert "order: 220" in source
    assert "onConversationOpenComplete:" in source
    assert "onConversationsRenderComplete:" in source
    assert "onVisitsRenderComplete:" in source
    assert "onPendingItemsRenderComplete:" in source
    assert "onRemindersRenderComplete:" in source
    assert 'runFeatureHook("onActivateCustomerTarget"' in source
    assert 'applyFeatureHook("onResolvePendingTarget"' in source
    assert "baseOpenConversationForCustomerActions" not in source
    assert "baseRenderConversationsForCustomerActions" not in source
    assert "baseRenderRequestListForTimeline" not in source
    assert "baseRenderPendingItemsForDetails" not in source
    assert "baseRenderRemindersForTargets" not in source
    assert "baseLogoutForCustomerActions" not in source
    assert "logout = function" not in source


def test_visits_are_loaded_by_section_and_visible_realtime_lifecycle(
    client: TestClient,
) -> None:
    source = portal_source(client, "visits.js")

    assert 'id: "visits"' in source
    assert "order: 350" in source
    assert 'sectionId === "visits-section"' in source
    assert "onRefreshComplete: renderVisitComposer" in source
    assert "onRealtime:" in source
    assert "onLogout: resetVisitState" in source
    assert 'applyFeatureHook("onVisitsRenderComplete"' in source
    assert 'document.querySelectorAll(".main-tab")' not in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source
    assert "setInterval" not in source
    assert "setTimeout" not in source


def test_party_experience_uses_lazy_lifecycle_and_preserves_scene_limits(
    client: TestClient,
) -> None:
    source = portal_source(client, "party-experience.js")

    assert 'id: "party-experience"' in source
    assert "order: 400" in source
    assert 'sectionId === "parties-section"' in source
    assert "onPetContextRefresh: updatePartyCreateState" in source
    assert "onRealtime:" in source
    assert "onLogout: resetPartyExperienceState" in source
    assert 'runFeatureHook("onPartiesRefreshComplete"' in source
    assert "[2, 3, 4]" in source
    assert "Math.min(2" in source
    assert "partyBaseRefreshAll" not in source
    assert "partyBaseRenderDashboard" not in source
    assert "refreshAll = async function" not in source
    assert "renderDashboard = function" not in source
    assert 'tab.addEventListener("click"' not in source
    assert "setTimeout" not in source
    assert "setInterval" not in source
    assert "new Worker" not in source
    assert "new WebSocket" not in source


def test_party_pending_uses_target_and_refresh_hooks_without_wrappers(
    client: TestClient,
) -> None:
    source = portal_source(client, "party-pending-experience.js")

    assert 'id: "party-pending"' in source
    assert "order: 410" in source
    assert "onResolvePendingTarget:" in source
    assert "onPendingItemDetailDecorated:" in source
    assert "onActivateCustomerTarget:" in source
    assert "onPartiesRefreshComplete:" in source
    assert "baseEnsurePendingItemsPanelForParties" not in source
    assert "baseActivateCustomerTargetForParties" not in source
    assert "basePendingTargetForParties" not in source
    assert "baseDecoratePendingItemDetailsForParties" not in source
    assert "baseRefreshPartiesForPendingItems" not in source
    assert "activateCustomerTarget = async function" not in source
    assert "pendingTarget = function" not in source
    assert "refreshParties = async function" not in source
