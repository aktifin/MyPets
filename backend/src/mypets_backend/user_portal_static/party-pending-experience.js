"use strict";

pendingKindLabels.party_invitation = "宠物聚会";

const baseEnsurePendingItemsPanelForParties = ensurePendingItemsPanel;
ensurePendingItemsPanel = function ensurePendingItemsPanelWithParties() {
  const panel = baseEnsurePendingItemsPanelForParties();
  const hint = panel?.querySelector(".section-heading .hint");
  if (hint) hint.textContent = "好友、共同照料、串门、宠物聚会和提醒集中在这里处理。";
  return panel;
};

const baseActivateCustomerTargetForParties = activateCustomerTarget;
activateCustomerTarget = async function activateCustomerTargetWithParty(kind, targetId, label = "") {
  if (kind === "party") {
    if (typeof ensurePartyExperience !== "function" || typeof openPartyDetail !== "function") {
      throw new Error("宠物聚会入口尚未准备完成，请刷新后重试。");
    }
    ensurePartyExperience();
    if (typeof partyActivateSection === "function") partyActivateSection();
    else activateCustomerSection("parties-section");
    await refreshParties();
    await openPartyDetail(targetId);
    return;
  }
  await baseActivateCustomerTargetForParties(kind, targetId, label);
};

const basePendingTargetForParties = pendingTarget;
pendingTarget = function pendingTargetWithParty(item) {
  if (item?.kind === "party_invitation") return { kind: "party", id: item.item_id };
  return basePendingTargetForParties(item);
};

const baseDecoratePendingItemDetailsForParties = decoratePendingItemDetails;
decoratePendingItemDetails = function decoratePendingItemDetailsWithParty() {
  baseDecoratePendingItemDetailsForParties();
  const list = $("pending-items-list");
  if (!list) return;
  [...list.children].forEach((card, index) => {
    const item = pendingItemsState.items[index];
    if (item?.kind !== "party_invitation") return;
    const button = card.querySelector(".pending-detail-button");
    if (button) button.textContent = "进入聚会";
  });
};

const baseRefreshPartiesForPendingItems = refreshParties;
refreshParties = async function refreshPartiesWithPendingItems() {
  await baseRefreshPartiesForPendingItems();
  if (accessToken) await refreshPendingItems();
};

ensurePendingItemsPanel();
renderPendingItems();
