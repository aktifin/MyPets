"use strict";

const assetSubmissionState = {
  items: [],
  loaded: false,
  loading: false,
  error: "",
};

const assetSubmissionUI = window.MyPetsPortalUI;
if (!assetSubmissionUI) throw new Error("MyPets 门户 UI 组件未加载");

function assetStatusLabel(value) {
  return {
    pending_processing: "等待处理",
    in_review: "审核中",
    approved: "已通过，等待人工制作",
    rejected: "已驳回",
  }[value] || value;
}

function assetStyleLabel(value) {
  return {
    original: "保留原画风",
    light_chibi: "轻度 Q 版",
    full_chibi: "完整 Q 版",
  }[value] || value;
}

function ensureAssetSubmissionWorkspace() {
  let section = $("asset-submissions-section");
  if (section) return section;
  const navigation = document.querySelector(".main-tabs");
  const appView = $("app-view");
  if (!navigation || !appView) return null;

  const tab = document.createElement("button");
  tab.className = "main-tab";
  tab.dataset.section = "asset-submissions-section";
  tab.type = "button";
  tab.textContent = "专属形象";
  navigation.append(tab);

  section = document.createElement("section");
  section.id = "asset-submissions-section";
  section.className = "workspace";
  section.hidden = true;
  section.tabIndex = -1;
  section.innerHTML = `
    <div class="two-column">
      <article class="panel">
        <div class="section-heading">
          <div><p class="eyebrow">SOURCE IMAGE</p><h2>提交宠物原图</h2></div>
          <span class="badge">静态图片</span>
        </div>
        <form id="asset-submission-form" class="compact-form">
          <label>宠物<select id="asset-submission-pet" required></select></label>
          <label>风格偏好
            <select id="asset-submission-style">
              <option value="original">保留原画风</option>
              <option value="light_chibi" selected>轻度 Q 版</option>
              <option value="full_chibi">完整 Q 版</option>
            </select>
          </label>
          <label>性格或识别提示<textarea id="asset-submission-personality" rows="3" maxlength="240" placeholder="例如：温柔、左耳有白色斑点"></textarea></label>
          <label>权利依据
            <select id="asset-submission-rights-basis">
              <option value="owner_photo">本人拍摄或本人拥有</option>
              <option value="authorized_use">已取得权利人明确授权</option>
            </select>
          </label>
          <label>图片<input id="asset-submission-file" type="file" accept="image/jpeg,image/png,image/webp" required></label>
          <label class="check-label"><input id="asset-submission-rights" type="checkbox" required>我确认拥有该图片的使用权或已取得授权，并同意服务端移除 EXIF/GPS 等元数据后保存。</label>
          <button id="asset-submission-submit" type="submit">提交审核</button>
        </form>
        <p class="hint">只接受单帧 JPEG、PNG 或 WebP。审核通过仅进入人工素材制作队列，不会立即替换宠物形象。</p>
      </article>

      <article class="panel">
        <div class="section-heading">
          <div><p class="eyebrow">SUBMISSIONS</p><h2>我的提交</h2></div>
          <button id="refresh-asset-submissions" class="secondary" type="button">刷新</button>
        </div>
        <div id="asset-submission-list" class="card-list"></div>
      </article>
    </div>`;
  appView.append(section);
  return section;
}

function installAssetSubmissionActions() {
  ensureAssetSubmissionWorkspace();
  const form = $("asset-submission-form");
  if (form && form.dataset.assetSubmissionBound !== "1") {
    form.dataset.assetSubmissionBound = "1";
    form.addEventListener("submit", submitPetAssetImage);
  }
  const refresh = $("refresh-asset-submissions");
  if (refresh && refresh.dataset.assetSubmissionBound !== "1") {
    refresh.dataset.assetSubmissionBound = "1";
    refresh.addEventListener("click", () => {
      assetSubmissionUI.runAction({
        control: refresh,
        statusNode: globalStatus,
        busyLabel: "正在刷新…",
        successMessage: "专属形象提交已刷新。",
        task: () => refreshAssetSubmissionWorkspace({ showLoading: true }),
      });
    });
  }
}

function renderAssetPetOptions() {
  ensureAssetSubmissionWorkspace();
  const select = $("asset-submission-pet");
  const submit = $("asset-submission-submit");
  if (!select || !submit) return;
  const previous = select.value;
  select.replaceChildren();
  const available = dashboard?.pets?.filter((item) => item.can_configure) || [];
  if (!available.length) {
    const option = node("option", "没有可提交形象的自有宠物");
    option.value = "";
    select.append(option);
    submit.disabled = true;
    return;
  }
  available.forEach((item) => {
    const option = node("option", `${item.pet.name} · ${roleLabel(item.relation.role)}`);
    option.value = item.pet.pet_id;
    select.append(option);
  });
  const preferred = available.some((item) => item.pet.pet_id === previous)
    ? previous
    : (dashboard?.selected_pet_id || available[0].pet.pet_id);
  select.value = preferred;
  submit.disabled = false;
}

function assetSubmissionRetryAction() {
  return {
    label: "重新读取",
    busyLabel: "正在读取…",
    onClick: () => refreshAssetSubmissionWorkspace({ showLoading: true }),
  };
}

function renderAssetSubmissions() {
  ensureAssetSubmissionWorkspace();
  const container = $("asset-submission-list");
  if (!container) return;
  assetSubmissionUI.setRegionBusy(container, assetSubmissionState.loading);

  if (assetSubmissionState.loading && !assetSubmissionState.loaded) {
    assetSubmissionUI.renderState(container, {
      kind: "loading",
      title: "正在读取专属形象提交",
      detail: "正在加载原图审核状态和人工制作准备信息。",
    });
    return;
  }
  if (assetSubmissionState.error && !assetSubmissionState.loaded) {
    assetSubmissionUI.renderState(container, {
      kind: "error",
      title: "专属形象提交读取失败",
      detail: assetSubmissionState.error,
      action: assetSubmissionRetryAction(),
    });
    return;
  }
  if (!assetSubmissionState.loaded) {
    assetSubmissionUI.renderState(container, {
      kind: "idle",
      title: "专属形象提交尚未读取",
      detail: "进入本页面后读取当前账户的原图提交记录。",
    });
    return;
  }

  container.replaceChildren();
  assetSubmissionUI.clearState(container);
  if (!assetSubmissionState.items.length) {
    assetSubmissionUI.renderState(container, {
      kind: "empty",
      title: "尚未提交宠物原图",
      detail: "选择自己管理的宠物并确认图片权利后，可以提交人工审核。",
    });
    return;
  }
  assetSubmissionState.items.forEach((item) => {
    const meta = [
      `${assetStatusLabel(item.status)} · ${assetStyleLabel(item.style_preference)}`,
      `${item.image_width}×${item.image_height} · ${(item.image_size / 1024).toFixed(1)} KB`,
      `提交时间：${new Date(item.created_at).toLocaleString()}`,
    ];
    if (item.review_comment) meta.push(`审核意见：${item.review_comment}`);
    const built = itemCard(item.pet_name, meta);
    built.actions.append(
      actionButton("下载已清理图片", () => downloadAssetSubmission(item), "secondary"),
    );
    container.append(built.card);
  });
  if (assetSubmissionState.error) {
    assetSubmissionUI.renderInlineNotice(container, {
      kind: "error",
      title: "最新提交状态暂未更新",
      detail: `${assetSubmissionState.error} 当前仍显示上次成功读取的记录。`,
      action: assetSubmissionRetryAction(),
    });
  }
}

async function refreshAssetSubmissions(options = {}) {
  ensureAssetSubmissionWorkspace();
  if (!accessToken) {
    resetAssetSubmissionState();
    return [];
  }
  const showLoading = options.showLoading ?? !assetSubmissionState.loaded;
  assetSubmissionState.loading = true;
  assetSubmissionState.error = "";
  if (showLoading || !assetSubmissionState.loaded) renderAssetSubmissions();
  else assetSubmissionUI.setRegionBusy($("asset-submission-list"), true);

  try {
    const payload = await api("/api/v1/pet-asset-submissions?limit=200");
    assetSubmissionState.items = Array.isArray(payload) ? payload : [];
    assetSubmissionState.loaded = true;
    return assetSubmissionState.items;
  } catch (error) {
    assetSubmissionState.error = error.message || "专属形象提交读取失败";
    throw error;
  } finally {
    assetSubmissionState.loading = false;
    renderAssetSubmissions();
  }
}

async function refreshAssetSubmissionWorkspace(options = {}) {
  if (!accessToken) {
    resetAssetSubmissionState();
    return;
  }
  if (!dashboard) await refreshDashboard();
  renderAssetPetOptions();
  await refreshAssetSubmissions(options);
}

async function downloadAssetSubmission(item) {
  const response = await fetch(item.image_url, {
    headers: { Authorization: `Bearer ${accessToken}`, Accept: item.image_media_type },
  });
  if (!response.ok) {
    let message = `下载失败（${response.status}）`;
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(message);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = item.image_media_type === "image/png"
    ? `pet-submission-${item.submission_id}.png`
    : `pet-submission-${item.submission_id}.jpg`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function resetAssetSubmissionForm() {
  const form = $("asset-submission-form");
  if (!form) return;
  form.reset();
  const style = $("asset-submission-style");
  const rightsBasis = $("asset-submission-rights-basis");
  if (style) style.value = "light_chibi";
  if (rightsBasis) rightsBasis.value = "owner_photo";
  renderAssetPetOptions();
}

async function submitPetAssetImage(event) {
  event.preventDefault();
  const file = $("asset-submission-file")?.files?.[0];
  if (!file) {
    setStatus(globalStatus, "请选择宠物图片。", "error");
    return;
  }
  if (!$("asset-submission-rights")?.checked) {
    setStatus(globalStatus, "必须确认图片权利。", "error");
    return;
  }
  const button = $("asset-submission-submit");
  assetSubmissionUI.runAction({
    control: button,
    statusNode: globalStatus,
    busyLabel: "正在提交…",
    task: async () => {
      const data = new FormData();
      data.append("pet_id", $("asset-submission-pet").value);
      data.append("style_preference", $("asset-submission-style").value);
      data.append("personality_hint", $("asset-submission-personality").value.trim());
      data.append("rights_basis", $("asset-submission-rights-basis").value);
      data.append("rights_confirmed", "true");
      data.append("image", file);
      const key = typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
      const created = await api("/api/v1/pet-asset-submissions", {
        method: "POST",
        headers: { "Idempotency-Key": `portal-asset-submission-${key}` },
        body: data,
      });
      resetAssetSubmissionForm();
      await refreshAssetSubmissions({ showLoading: false });
      setStatus(globalStatus, `${created.pet_name} 的原图已安全提交。`, "success");
    },
  });
}

function resetAssetSubmissionState() {
  assetSubmissionState.items = [];
  assetSubmissionState.loaded = false;
  assetSubmissionState.loading = false;
  assetSubmissionState.error = "";
  renderAssetSubmissions();
  renderAssetPetOptions();
}

portalRuntime.registerFeature({
  id: "asset-submissions",
  label: "专属形象提交",
  order: 330,
  mount: () => {
    ensureAssetSubmissionWorkspace();
    installAssetSubmissionActions();
    renderAssetPetOptions();
    renderAssetSubmissions();
  },
  onRefreshComplete: renderAssetPetOptions,
  onPetContextRefresh: renderAssetPetOptions,
  onSectionEnter: async ({ sectionId, source }) => {
    if (
      sectionId === "asset-submissions-section"
      && accessToken
      && source !== "anonymous"
    ) {
      await refreshAssetSubmissionWorkspace({
        showLoading: !assetSubmissionState.loaded,
      });
    }
  },
  onRealtime: async () => {
    const section = $("asset-submissions-section");
    if (!accessToken || !section || section.hidden || !assetSubmissionState.loaded) return;
    await refreshAssetSubmissions({ showLoading: false });
  },
  onLogout: resetAssetSubmissionState,
});
