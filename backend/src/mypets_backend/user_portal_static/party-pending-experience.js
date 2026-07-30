"use strict";

pendingKindLabels.party_invitation = "宠物聚会";

function updatePartyPendingHint() {
  const panel = ensurePendingItemsPanel();
  const hint = panel?.querySelector(".section-heading .hint");
  if (hint) {
    hint.textContent = "好友、共同照料、串门、宠物聚会和提醒集中在这里处理。";
  }
}

portalRuntime.registerFeature({
  id: "party-pending",
  label: "聚会邀请待办",
  order: 410,
  mount: () => {
    updatePartyPendingHint();
    renderPendingItems();
  },
  onResolvePendingTarget: (context) => {
    if (context.item?.kind === "party_invitation") {
      context.target = {
        kind: "party",
        id: context.item.item_id,
      };
    }
  },
  onPendingItemDetailDecorated: ({ item, button }) => {
    if (item?.kind === "party_invitation" && button) {
      button.textContent = "进入聚会";
    }
  },
  onActivateCustomerTarget: async (context) => {
    if (context.kind !== "party") return;
    ensurePartyExperience();
    partyActivateSection("party-pending-target");
    await refreshParties("pending-target");
    context.result = await openPartyDetail(context.targetId);
    context.handled = true;
  },
  onPartiesRefreshComplete: async () => {
    if (accessToken) await refreshPendingItems();
  },
  onPendingItemsRenderComplete: updatePartyPendingHint,
});
