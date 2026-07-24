"use strict";

const state = {
  token: sessionStorage.getItem("mypetsAdminToken") || "",
  account: null,
  templates: [],
  versions: [],
  selectedTemplate: null,
  selectedVersion: null,
  preview: null,
  releases: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const titles = {dashboard:"总览",templates:"宠物模板",reviews:"审核中心",releases:"发布历史",audit:"审计日志"};
const statusNames = {draft:"草稿",in_review:"审核中",changes_required:"需修改",approved:"已批准",published:"已发布"};
const actionNames = {idle:"待机",walk:"行走",sit:"坐下",sleep:"睡眠",wave:"挥手",happy:"开心",shy:"害羞",surprised:"惊讶",annoyed:"生气",sleepy:"困倦",curious:"好奇",selfie:"自拍",drag:"拖动"};

function escapeHtml(value){return String(value??"").replace(/[&<>'"]/g,(char)=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));}
function formatDate(value){if(!value)return "—";return new Intl.DateTimeFormat("zh-CN",{dateStyle:"medium",timeStyle:"short"}).format(new Date(value));}
function formatBytes(value){if(value===null||value===undefined)return "—";if(value<1024)return `${value} B`;if(value<1048576)return `${(value/1024).toFixed(1)} KB`;return `${(value/1048576).toFixed(1)} MB`;}
function badge(status){return `<span class="badge ${escapeHtml(status)}">${escapeHtml(statusNames[status]||status)}</span>`;}
function setStatus(message,isError=false){const node=$("#globalStatus");node.textContent=message||"";node.classList.toggle("error",isError);}
function errorMessage(error){if(error&&error.message)return error.message;return "请求失败";}

async function api(path,options={}){
  const headers=new Headers(options.headers||{});
  if(state.token)headers.set("Authorization",`Bearer ${state.token}`);
  if(options.json!==undefined){headers.set("Content-Type","application/json");options.body=JSON.stringify(options.json);}
  const response=await fetch(path,{...options,headers});
  if(response.status===401){logout();throw new Error("登录已过期，请重新登录");}
  if(!response.ok){let detail=`请求失败（${response.status}）`;try{const data=await response.json();detail=typeof data.detail==="string"?data.detail:detail;}catch{}throw new Error(detail);}
  if(response.status===204)return null;
  return response.json();
}

async function login(username,password){
  const body=new URLSearchParams({username,password});
  const response=await fetch("/api/v1/auth/token",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body});
  if(!response.ok){let detail="用户名或密码错误";try{detail=(await response.json()).detail||detail;}catch{}throw new Error(detail);}
  const payload=await response.json();
  state.token=payload.access_token;
  state.account=payload.account;
  sessionStorage.setItem("mypetsAdminToken",state.token);
  await api("/api/v1/admin/pet-templates");
}

function logout(){
  state.token="";state.account=null;state.templates=[];state.versions=[];state.selectedTemplate=null;state.selectedVersion=null;
  sessionStorage.removeItem("mypetsAdminToken");
  $("#appView").classList.add("hidden");$("#loginView").classList.remove("hidden");$("#password").value="";
}

async function bootstrap(){
  if(!state.token){logout();return;}
  try{
    state.account=await api("/api/v1/accounts/me");
    await loadTemplates();
    $("#accountName").textContent=state.account.display_name||state.account.username;
    $("#loginView").classList.add("hidden");$("#appView").classList.remove("hidden");
    await showView("dashboard");
  }catch(error){logout();$("#loginError").textContent=errorMessage(error);}
}

async function loadTemplates(){
  state.templates=await api("/api/v1/admin/pet-templates");
  renderTemplateList();
  return state.templates;
}

function renderTemplateList(){
  const query=$("#templateSearch").value.trim().toLowerCase();
  const rows=state.templates.filter(item=>[item.template_code,item.display_name,item.species].some(value=>String(value).toLowerCase().includes(query)));
  $("#templateList").innerHTML=rows.length?rows.map(item=>`<button class="item-card ${state.selectedTemplate?.id===item.id?"active":""}" data-template-id="${item.id}"><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.template_code)} · ${escapeHtml(item.species)}</small></button>`).join(""):`<div class="empty-row">没有匹配的模板</div>`;
  $$("[data-template-id]").forEach(button=>button.addEventListener("click",()=>selectTemplate(button.dataset.templateId)));
}

async function selectTemplate(templateId){
  state.selectedTemplate=state.templates.find(item=>item.id===templateId)||null;
  state.selectedVersion=null;state.preview=null;
  if(!state.selectedTemplate)return;
  setStatus("正在读取模板版本…");
  try{
    state.versions=await api(`/api/v1/admin/pet-templates/${templateId}/versions`);
    renderTemplateList();renderTemplateWorkspace();setStatus("");
  }catch(error){setStatus(errorMessage(error),true);}
}

function renderTemplateWorkspace(){
  const item=state.selectedTemplate;
  $("#templateEmpty").classList.toggle("hidden",!!item);$("#templateWorkspace").classList.toggle("hidden",!item);
  if(!item)return;
  $("#templateCode").textContent=`${item.template_code} · ${item.species}`;$("#templateName").textContent=item.display_name;$("#templateDescription").textContent=item.description||"暂无模板说明";
  $("#templateStatus").outerHTML=badgeWithId("templateStatus",item.status);
  $("#versionList").innerHTML=state.versions.length?state.versions.map(version=>`<button class="version-card ${state.selectedVersion?.id===version.id?"active":""}" data-version-id="${version.id}"><header><strong>${escapeHtml(version.template_version)}</strong>${badge(version.status)}</header><p>身份 ${escapeHtml(version.identity_version)} · 素材 ${escapeHtml(version.asset_version)}</p></button>`).join(""):`<div class="empty-row">尚未创建版本</div>`;
  $$("[data-version-id]").forEach(button=>button.addEventListener("click",()=>selectVersion(button.dataset.versionId)));
  $("#versionDetail").classList.toggle("hidden",!state.selectedVersion);
  if(state.selectedVersion)renderVersionDetail();
}

function badgeWithId(id,status){return `<span id="${id}" class="badge ${escapeHtml(status)}">${escapeHtml(statusNames[status]||status)}</span>`;}

async function selectVersion(versionId){
  state.selectedVersion=state.versions.find(item=>item.id===versionId)||await api(`/api/v1/admin/pet-template-versions/${versionId}`);
  state.preview=null;renderTemplateWorkspace();
  if(state.selectedVersion.package_sha256)await loadPreview();
}

function actionButton(label,action,kind="secondary"){return `<button class="${kind} compact" data-version-action="${action}">${label}</button>`;}
function renderVersionDetail(){
  const version=state.selectedVersion;if(!version)return;
  $("#versionIdentity").textContent=`模板 ${version.template_version} · 身份 ${version.identity_version} · 素材 ${version.asset_version}`;
  $("#versionTitle").textContent=`版本 ${version.template_version}`;$("#versionStatus").outerHTML=badgeWithId("versionStatus",version.status);
  $("#packageSize").textContent=formatBytes(version.package_size);$("#packageHash").textContent=version.package_sha256||"—";$("#reviewComment").textContent=version.review_comment||"—";
  const actions=[];
  if(["draft","changes_required"].includes(version.status))actions.push(actionButton("提交审核","submit","primary"));
  if(version.status==="in_review"){actions.push(actionButton("批准","approve","primary"));actions.push(actionButton("退回修改","reject"));}
  if(version.status==="approved")actions.push(actionButton("正式发布","publish","primary"));
  $("#versionActions").innerHTML=actions.join("");
  $$("[data-version-action]").forEach(button=>button.addEventListener("click",()=>runVersionAction(button.dataset.versionAction)));
  $("#uploadArea").classList.toggle("hidden",!["draft","changes_required"].includes(version.status));
  renderPreview();
}

async function loadPreview(){
  if(!state.selectedVersion)return;
  try{state.preview=await api(`/api/v1/admin/pet-template-versions/${state.selectedVersion.id}/preview`);renderPreview();}
  catch(error){state.preview=null;setStatus(errorMessage(error),true);}
}

function renderPreview(){
  const preview=state.preview;$("#previewArea").classList.toggle("hidden",!preview);if(!preview)return;
  $("#previewAction").innerHTML=preview.actions.map(item=>`<option value="${escapeHtml(item.name)}">${escapeHtml(actionNames[item.name]||item.name)}${item.fallback_to?`（降级到 ${escapeHtml(item.source_action)}）`:""}</option>`).join("");
  $("#actionMatrix").innerHTML=preview.actions.map(item=>`<div class="matrix-item"><strong>${escapeHtml(actionNames[item.name]||item.name)}</strong><small>${item.fallback_to?`降级 → ${escapeHtml(item.source_action)}`:`原生 · ${item.frame_count} 帧`}</small></div>`).join("");
  refreshPreviewImage();
}
function refreshPreviewImage(){
  if(!state.selectedVersion||!state.preview)return;
  const action=$("#previewAction").value||"idle";const frame=Math.max(0,Number.parseInt($("#previewFrame").value||"0",10));
  $("#previewImage").src=`/api/v1/admin/pet-template-versions/${state.selectedVersion.id}/preview-image?action=${encodeURIComponent(action)}&frame_index=${frame}&access_token=${encodeURIComponent(state.token)}`;
}

async function runVersionAction(action){
  if(!state.selectedVersion)return;
  if(action==="approve"||action==="reject"){
    $("#reviewVersionId").value=state.selectedVersion.id;$("#reviewDecision").value=action;$("#reviewDialogTitle").textContent=action==="approve"?"批准宠物版本":"退回宠物版本";$("#reviewDecisionComment").value="";$("#reviewDialog").showModal();return;
  }
  if(action==="publish"&&!confirm("发布后素材包不可覆盖。确认正式发布该版本？"))return;
  setStatus("正在更新版本状态…");
  try{
    const result=await api(`/api/v1/admin/pet-template-versions/${state.selectedVersion.id}/${action==="submit"?"submit-review":"publish"}`,{method:"POST"});
    await selectTemplate(state.selectedTemplate.id);state.selectedVersion=state.versions.find(item=>item.id===(result.id||state.selectedVersion.id))||state.selectedVersion;renderTemplateWorkspace();setStatus(action==="publish"?"发布完成":"状态已更新");
  }catch(error){setStatus(errorMessage(error),true);}
}

function uploadPackage(){
  const file=$("#packageFile").files[0];if(!file||!state.selectedVersion){setStatus("请选择 ZIP 素材包",true);return;}
  const xhr=new XMLHttpRequest();const form=new FormData();form.append("package",file);
  xhr.open("POST",`/api/v1/admin/pet-template-versions/${state.selectedVersion.id}/package`);xhr.setRequestHeader("Authorization",`Bearer ${state.token}`);
  xhr.upload.onprogress=(event)=>{if(event.lengthComputable)$("#uploadProgress").style.width=`${Math.round(event.loaded/event.total*100)}%`;};
  xhr.onload=async()=>{if(xhr.status>=200&&xhr.status<300){state.selectedVersion=JSON.parse(xhr.responseText);state.versions=state.versions.map(item=>item.id===state.selectedVersion.id?state.selectedVersion:item);$("#uploadProgress").style.width="100%";renderTemplateWorkspace();await loadPreview();setStatus("素材包已上传并通过服务端校验");}else{let message=`上传失败（${xhr.status}）`;try{message=JSON.parse(xhr.responseText).detail||message;}catch{}setStatus(message,true);}};
  xhr.onerror=()=>setStatus("素材包上传失败",true);setStatus("正在上传并校验素材包…");xhr.send(form);
}

async function loadAllVersions(status=""){
  const query=status?`?status=${encodeURIComponent(status)}`:"";return api(`/api/v1/admin/pet-template-versions${query}`);
}
async function loadReleases(){state.releases=await api("/api/v1/admin/pet-asset-releases");renderReleases();return state.releases;}
function renderReleases(){
  $("#releaseList").innerHTML=state.releases.length?`<table><thead><tr><th>模板</th><th>模板版本</th><th>身份 / 素材</th><th>大小</th><th>发布时间</th><th>包</th></tr></thead><tbody>${state.releases.map(item=>`<tr><td>${escapeHtml(item.template_id)}</td><td>${escapeHtml(item.template_version)}</td><td>${escapeHtml(item.identity_version)} / ${escapeHtml(item.asset_version)}</td><td>${formatBytes(item.package_size)}</td><td>${formatDate(item.published_at)}</td><td><a class="preview-link" href="${escapeHtml(item.download_url)}">下载</a></td></tr>`).join("")}</tbody></table>`:`<div class="empty-row">暂无发布记录</div>`;
}

async function renderReviews(){
  const reviews=await loadAllVersions("in_review");
  $("#reviewList").innerHTML=reviews.length?reviews.map(item=>{const template=state.templates.find(t=>t.id===item.template_id);return `<div class="review-card"><div><div>${badge(item.status)}</div><h3>${escapeHtml(template?.display_name||item.template_id)} · ${escapeHtml(item.template_version)}</h3><p>身份 ${escapeHtml(item.identity_version)} · 素材 ${escapeHtml(item.asset_version)} · ${formatBytes(item.package_size)}</p></div><div class="button-row"><button class="secondary compact" data-review-open="${item.id}">查看</button><button class="primary compact" data-review-approve="${item.id}">批准</button><button class="secondary compact" data-review-reject="${item.id}">退回</button></div></div>`;}).join(""):`<div class="empty-row">当前没有待审核版本</div>`;
  $$("[data-review-open]").forEach(button=>button.addEventListener("click",async()=>{const version=reviews.find(item=>item.id===button.dataset.reviewOpen);state.selectedTemplate=state.templates.find(item=>item.id===version.template_id);await selectTemplate(version.template_id);await selectVersion(version.id);showView("templates");}));
  for(const decision of ["approve","reject"]){$$(`[data-review-${decision}]`).forEach(button=>button.addEventListener("click",()=>{$("#reviewVersionId").value=button.dataset[`review${decision[0].toUpperCase()+decision.slice(1)}`];$("#reviewDecision").value=decision;$("#reviewDialogTitle").textContent=decision==="approve"?"批准宠物版本":"退回宠物版本";$("#reviewDecisionComment").value="";$("#reviewDialog").showModal();}));}
}

async function renderAudit(){
  const rows=await api("/api/v1/admin/audit-logs?limit=200");
  $("#auditList").innerHTML=rows.length?`<table><thead><tr><th>时间</th><th>动作</th><th>资源</th><th>管理员</th><th>详情</th></tr></thead><tbody>${rows.map(item=>`<tr><td>${formatDate(item.created_at)}</td><td>${escapeHtml(item.action)}</td><td>${escapeHtml(item.resource_type)}<br><code>${escapeHtml(item.resource_id)}</code></td><td><code>${escapeHtml(item.admin_account_id)}</code></td><td><code>${escapeHtml(JSON.stringify(item.details))}</code></td></tr>`).join("")}</tbody></table>`:`<div class="empty-row">暂无审计记录</div>`;
}

async function renderDashboard(){
  const [reviews,releases]=await Promise.all([loadAllVersions("in_review"),loadReleases()]);
  const versions=await loadAllVersions();
  const cards=[['模板总数',state.templates.length],['版本总数',versions.length],['待审核',reviews.length],['已发布',releases.length]];
  $("#summaryCards").innerHTML=cards.map(([name,value])=>`<div class="summary-card"><span>${name}</span><strong>${value}</strong></div>`).join("");
  $("#dashboardReviews").innerHTML=reviews.length?reviews.slice(0,5).map(item=>`<div class="item-card"><strong>${escapeHtml(item.template_version)}</strong><small>${escapeHtml(item.identity_version)} / ${escapeHtml(item.asset_version)}</small></div>`).join(""):`<div class="empty-row">没有待审核版本</div>`;
  $("#dashboardReleases").innerHTML=releases.length?releases.slice(0,5).map(item=>`<div class="item-card"><strong>${escapeHtml(item.template_id)}</strong><small>${escapeHtml(item.asset_version)} · ${formatDate(item.published_at)}</small></div>`).join(""):`<div class="empty-row">暂无发布记录</div>`;
}

async function showView(name){
  $$(".view-panel").forEach(panel=>panel.classList.add("hidden"));$(`#${name}View`).classList.remove("hidden");
  $$("#navigation button").forEach(button=>button.classList.toggle("active",button.dataset.view===name));$("#viewTitle").textContent=titles[name]||name;
  setStatus("正在加载…");
  try{
    if(name==="dashboard")await renderDashboard();
    if(name==="templates"){await loadTemplates();renderTemplateWorkspace();}
    if(name==="reviews"){await loadTemplates();await renderReviews();}
    if(name==="releases")await loadReleases();
    if(name==="audit")await renderAudit();
    setStatus("");
  }catch(error){setStatus(errorMessage(error),true);}
}

$("#loginForm").addEventListener("submit",async(event)=>{event.preventDefault();$("#loginError").textContent="";try{await login($("#username").value,$("#password").value);$("#accountName").textContent=state.account.display_name||state.account.username;$("#loginView").classList.add("hidden");$("#appView").classList.remove("hidden");await showView("dashboard");}catch(error){$("#loginError").textContent=errorMessage(error);}});
$("#logoutButton").addEventListener("click",logout);$("#navigation").addEventListener("click",event=>{const button=event.target.closest("[data-view]");if(button)showView(button.dataset.view);});$$('[data-jump]').forEach(button=>button.addEventListener("click",()=>showView(button.dataset.jump)));
$("#templateSearch").addEventListener("input",renderTemplateList);$("#newTemplateButton").addEventListener("click",()=>$("#templateDialog").showModal());$("#newVersionButton").addEventListener("click",()=>$("#versionDialog").showModal());
$("#templateForm").addEventListener("submit",async(event)=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.currentTarget));try{const created=await api("/api/v1/admin/pet-templates",{method:"POST",json:data});event.currentTarget.reset();$("#templateDialog").close();await loadTemplates();await selectTemplate(created.id);setStatus("模板已创建");}catch(error){setStatus(errorMessage(error),true);}});
$("#versionForm").addEventListener("submit",async(event)=>{event.preventDefault();if(!state.selectedTemplate)return;const data=Object.fromEntries(new FormData(event.currentTarget));try{const created=await api(`/api/v1/admin/pet-templates/${state.selectedTemplate.id}/versions`,{method:"POST",json:data});$("#versionDialog").close();await selectTemplate(state.selectedTemplate.id);await selectVersion(created.id);setStatus("模板版本已创建");}catch(error){setStatus(errorMessage(error),true);}});
$("#uploadButton").addEventListener("click",uploadPackage);$("#refreshPreview").addEventListener("click",refreshPreviewImage);$("#previewAction").addEventListener("change",()=>{$("#previewFrame").value="0";refreshPreviewImage();});
$("#reviewForm").addEventListener("submit",async(event)=>{event.preventDefault();const id=$("#reviewVersionId").value;const decision=$("#reviewDecision").value;try{await api(`/api/v1/admin/pet-template-versions/${id}/${decision}`,{method:"POST",json:{comment:$("#reviewDecisionComment").value}});$("#reviewDialog").close();if(state.selectedTemplate)await selectTemplate(state.selectedTemplate.id);await renderReviews();setStatus(decision==="approve"?"版本已批准":"版本已退回");}catch(error){setStatus(errorMessage(error),true);}});
$("#refreshReviews").addEventListener("click",renderReviews);$("#refreshReleases").addEventListener("click",loadReleases);$("#refreshAudit").addEventListener("click",renderAudit);
$$('dialog button[value="cancel"]').forEach(button=>button.addEventListener("click",event=>{event.preventDefault();button.closest("dialog").close();}));

bootstrap();
