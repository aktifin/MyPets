"use strict";

(() => {
  const PROTOCOL = "mypets.realtime.v1";
  const TICKET_PREFIX = "mypets.ticket.";
  let socket = null;
  let reconnectTimer = null;
  let reconnectDelayMs = 1000;
  let refreshTimer = null;
  let stopped = false;

  function statusText(message) {
    const label = document.getElementById("session-label");
    if (!label || !message) return;
    label.title = message;
  }

  function websocketUrl() {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}/api/v1/realtime/ws`;
  }

  async function issueTicket() {
    const response = await api("/api/v1/realtime/ticket", { method: "POST" });
    if (!response || typeof response.ticket !== "string" || response.protocol !== PROTOCOL) {
      throw new Error("实时连接票据响应无效");
    }
    return response.ticket;
  }

  function stopRealtime() {
    stopped = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    if (refreshTimer) window.clearTimeout(refreshTimer);
    reconnectTimer = null;
    refreshTimer = null;
    if (socket) {
      const current = socket;
      socket = null;
      current.onclose = null;
      current.close(1000, "portal logout");
    }
    statusText("实时通知未连接");
  }

  function scheduleReconnect() {
    if (stopped || !accessToken || reconnectTimer) return;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connectRealtime().catch(() => scheduleReconnect());
    }, reconnectDelayMs);
    reconnectDelayMs = Math.min(reconnectDelayMs * 2, 30000);
  }

  async function refreshFromRealtime(cursor) {
    if (!accessToken) return;
    try {
      const tasks = [refreshDashboard(), refreshSocial()];
      if (typeof refreshVisits === "function") tasks.push(refreshVisits());
      await Promise.all(tasks);
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "ack", cursor }));
      }
      statusText(`实时数据已刷新至游标 ${cursor}`);
    } catch (error) {
      setStatus(globalStatus, `实时刷新失败：${error.message}`, "error");
    }
  }

  function queueRefresh(cursor) {
    if (refreshTimer) window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => {
      refreshTimer = null;
      refreshFromRealtime(cursor);
    }, 250);
  }

  async function connectRealtime() {
    if (!accessToken || stopped || (socket && socket.readyState <= WebSocket.OPEN)) return;
    const ticket = await issueTicket();
    const value = new WebSocket(websocketUrl(), [PROTOCOL, `${TICKET_PREFIX}${ticket}`]);
    socket = value;

    value.onopen = () => {
      reconnectDelayMs = 1000;
      statusText("实时通知已连接");
    };
    value.onmessage = (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (_error) {
        return;
      }
      if (!payload || typeof payload !== "object") return;
      if (payload.type === "events_available" && Number.isInteger(payload.cursor)) {
        queueRefresh(payload.cursor);
      } else if (payload.type === "heartbeat") {
        value.send(JSON.stringify({ type: "ack", cursor: Number(payload.cursor) || 0 }));
      }
    };
    value.onerror = () => statusText("实时通知连接异常，页面仍可手动刷新");
    value.onclose = () => {
      if (socket === value) socket = null;
      statusText("实时通知已断开，正在尝试恢复");
      scheduleReconnect();
    };
  }

  const originalEnterApp = enterApp;
  enterApp = function enterAppWithRealtime() {
    originalEnterApp();
    stopped = false;
    window.setTimeout(() => connectRealtime().catch(() => scheduleReconnect()), 0);
  };

  const originalLogout = logout;
  logout = function logoutWithRealtime(...args) {
    stopRealtime();
    return originalLogout(...args);
  };

  window.addEventListener("online", () => {
    if (accessToken) {
      stopped = false;
      connectRealtime().catch(() => scheduleReconnect());
    }
  });
  window.addEventListener("offline", () => statusText("网络离线，等待恢复实时通知"));
  window.addEventListener("beforeunload", stopRealtime);

  if (accessToken) {
    stopped = false;
    window.setTimeout(() => connectRealtime().catch(() => scheduleReconnect()), 0);
  }
})();
