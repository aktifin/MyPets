"use strict";

(() => {
  const STATE_DEFAULTS = {
    idle: {
      title: "尚未读取",
      detail: "进入页面或手动刷新后显示最新内容。",
      symbol: "–",
    },
    loading: {
      title: "正在加载",
      detail: "正在从服务端读取最新内容。",
      symbol: "…",
    },
    empty: {
      title: "暂无内容",
      detail: "当前范围内没有可显示的数据。",
      symbol: "○",
    },
    error: {
      title: "加载失败",
      detail: "暂时无法读取内容，请稍后重试。",
      symbol: "!",
    },
    info: {
      title: "提示",
      detail: "",
      symbol: "i",
    },
  };

  function uiNode(tag, text = "", className = "") {
    const value = document.createElement(tag);
    if (text) value.textContent = text;
    if (className) value.className = className;
    return value;
  }

  function setRegionBusy(container, busy) {
    if (!container) return;
    if (busy) container.setAttribute("aria-busy", "true");
    else container.removeAttribute("aria-busy");
  }

  function clearState(container) {
    if (!container) return;
    delete container.dataset.portalUiState;
    setRegionBusy(container, false);
  }

  async function runAction(options = {}) {
    const {
      control = null,
      statusNode = null,
      task,
      busyLabel = "",
      successMessage = "",
      clearStatus = true,
    } = options;
    if (typeof task !== "function") {
      throw new TypeError("runAction 需要 task 函数");
    }

    const previousDisabled = control?.disabled;
    const previousLabel = control?.textContent || "";
    if (control) {
      control.disabled = true;
      control.dataset.portalUiBusy = "1";
      control.setAttribute("aria-busy", "true");
      if (busyLabel) control.textContent = busyLabel;
    }
    if (statusNode && clearStatus && typeof setStatus === "function") {
      setStatus(statusNode, "");
    }

    try {
      const value = await task();
      if (statusNode && successMessage && typeof setStatus === "function") {
        setStatus(statusNode, successMessage, "success");
      }
      return { ok: true, value };
    } catch (error) {
      if (statusNode && typeof setStatus === "function") {
        setStatus(statusNode, error.message || "操作失败", "error");
      } else {
        console.error("[MyPetsPortalUI] action failed", error);
      }
      return { ok: false, error };
    } finally {
      if (control) {
        control.disabled = Boolean(previousDisabled);
        delete control.dataset.portalUiBusy;
        control.removeAttribute("aria-busy");
        if (busyLabel) control.textContent = previousLabel;
      }
    }
  }

  function renderState(container, options = {}) {
    if (!container) return null;
    const kind = STATE_DEFAULTS[options.kind] ? options.kind : "info";
    const defaults = STATE_DEFAULTS[kind];
    const state = uiNode(
      "div",
      "",
      `portal-ui-state portal-ui-state-${kind}${options.compact ? " compact" : ""}`,
    );
    state.dataset.state = kind;
    state.setAttribute("role", kind === "error" ? "alert" : "status");
    state.setAttribute("aria-live", kind === "error" ? "assertive" : "polite");

    const symbol = uiNode(
      "span",
      options.symbol || defaults.symbol,
      `portal-ui-state-symbol${kind === "loading" ? " loading" : ""}`,
    );
    symbol.setAttribute("aria-hidden", "true");
    const copy = uiNode("div", "", "portal-ui-state-copy");
    copy.append(
      uiNode("strong", options.title || defaults.title),
      uiNode("p", options.detail ?? defaults.detail),
    );
    state.append(symbol, copy);

    if (options.action && typeof options.action.onClick === "function") {
      const button = uiNode(
        "button",
        options.action.label || "重试",
        options.action.className || "secondary compact",
      );
      button.type = "button";
      button.addEventListener("click", () => {
        runAction({
          control: button,
          busyLabel: options.action.busyLabel || "正在重试…",
          task: options.action.onClick,
        });
      });
      state.append(button);
    }

    container.replaceChildren(state);
    container.dataset.portalUiState = kind;
    setRegionBusy(container, kind === "loading");
    return state;
  }

  function renderInlineNotice(container, options = {}) {
    if (!container) return null;
    container.querySelector(":scope > .portal-ui-inline-notice")?.remove();
    const notice = renderState(document.createElement("div"), {
      ...options,
      compact: true,
    });
    if (!notice) return null;
    notice.classList.add("portal-ui-inline-notice");
    container.prepend(notice);
    return notice;
  }

  window.MyPetsPortalUI = Object.freeze({
    clearState,
    renderInlineNotice,
    renderState,
    runAction,
    setRegionBusy,
  });
})();
