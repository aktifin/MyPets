"use strict";

window.setTimeout(async () => {
  if (!accessToken) return;
  try {
    if (!dashboard) await refreshDashboard();
    await refreshPortalPhase1();
  } catch (error) {
    if (accessToken) setStatus(globalStatus, error.message, "error");
  }
}, 0);
