"use strict";
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pretty = value => JSON.stringify(value, null, 2);
const labels = {completed:"检查通过",needs_information:"待补充信息",needs_materials:"待补充素材",failed:"工具失败",constraints_unmet:"无法满足",incomplete:"尚未完成",approved:"编辑校验通过",rejected:"编辑未通过"};
const toolNames = {inspect_request:"核对需求",search_materials:"检索素材",read_material:"读取原文",draft_script:"生成分镜",revise_script:"修订脚本",estimate_duration:"估算时长",check_brand_rules:"检查事实与规则",finish:"交付脚本",request_information:"请求补充",stop:"停止任务"};
const riskLabels = {brand_prohibited_term:"包含品牌禁用词",claim_text_not_supported:"产品主张与素材原文不符",unverified_copy:"新文案需要人工审查",unverified_title:"标题缺少依据或需要人工审查",unverified_visual:"画面说明缺少依据",unknown_fact_reference:"引用的事实不存在",no_grounded_product_fact:"缺少可追溯产品事实",changed_user_requirement:"改变了用户要求",unsupported_platform:"平台尚不支持",missing_required_input:"创作需求不完整",invalid_script_shape:"脚本格式无效",hold_seconds_must_be_integer_0_to_60:"停留时间须为0至60的整数"};
let config, envelope = null, draft = null, approved = false, editing = false, checking = false, editVersion = 0, manual = null;
async function api(url, body) {
  const response = await fetch(url, body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "本机服务请求失败。");
  return data;
}
function error(message) { $("error-banner").hidden = !message; $("error-banner").textContent = message || ""; }
function selectCase(name) {
  const item = config.cases.find(x => x.id === name);
  $("case").value = name;
  for (const key of ["theme","audience","platform","style"]) $(key).value = item.request[key] ?? "";
  $("target").value = item.request.target_seconds ?? "";
  $("max-steps").value = item.max_steps;
  document.querySelectorAll("[data-case]").forEach(b => b.classList.toggle("selected", b.dataset.case === name));
}
function status(value, note) {
  $("metric-status").textContent = labels[value] || value;
  $("metric-status").className = ["completed","approved"].includes(value) ? "state-completed" : ["failed","rejected","constraints_unmet"].includes(value) ? "state-failed" : "state-incomplete";
  $("metric-mode").textContent = note;
}
function renderEditor() {
  if (!draft) { $("storyboard").innerHTML = '<div class="detail-placeholder">本轮没有生成脚本，请查看风险与缺口。</div>'; return; }
  const timings = manual?.validation.duration_check.shots || envelope.result.duration_check?.shots || [];
  $("storyboard").innerHTML = `<label class="editor-title-label" for="script-title">脚本标题</label><input id="script-title" value="${escapeHTML(draft.title)}" maxlength="1000"><div class="script-meta">${escapeHTML(draft.audience)} · ${escapeHTML(draft.platform)} · ${escapeHTML(draft.style)}</div>` + draft.shots.map((s,i) => {
    const timing = timings.find(t => t.shot_id === s.shot_id);
    return `<article class="shot-card"><div class="shot-heading"><span class="shot-number">${escapeHTML(s.shot_id)}</span><b>${escapeHTML(s.visual)}</b><span class="shot-seconds">${timing ? timing.estimated_seconds + " 秒" : "待估算"}</span></div><div class="shot-copy"><div><label for="narration-${i}">旁白</label><textarea id="narration-${i}" data-index="${i}" data-field="narration" rows="2" maxlength="1000">${escapeHTML(s.narration)}</textarea></div><div><label for="subtitle-${i}">字幕</label><textarea id="subtitle-${i}" data-index="${i}" data-field="subtitle" rows="2" maxlength="1000">${escapeHTML(s.subtitle)}</textarea></div></div><div class="shot-bottom"><span>${s.fact_ids.length ? s.fact_ids.map(escapeHTML).join(" · ") : "中性创作文案 · 非产品事实"}</span><label for="hold-${i}">额外停留 <input id="hold-${i}" data-index="${i}" data-field="hold_seconds" type="number" min="0" max="60" value="${s.hold_seconds}"> 秒</label></div></article>`;
  }).join("");
  $("script-title").addEventListener("input", event => { draft.title = event.target.value; markDirty(); });
  document.querySelectorAll("[data-field]").forEach(input => input.addEventListener("input", event => {
    draft.shots[Number(input.dataset.index)][input.dataset.field] = input.dataset.field === "hold_seconds" ? (input.value === "" ? null : Number(input.value)) : event.target.value;
    markDirty();
  }));
}
function markDirty() {
  editVersion++; approved = false; editing = true; manual = null;
  status("编辑待校验", "内容已修改，旧的检查不再适用");
  $("metric-duration").textContent = "待检";
  document.querySelectorAll(".shot-seconds").forEach(x => x.textContent = "待估算");
  $("edit-notice").hidden = false;
  $("edit-notice").textContent = "编辑尚未通过检查。点击“校验我的修改”重新计算时长并核对事实。";
  $("validation-result").replaceChildren();
  updateButtons();
}
function updateButtons() {
  $("validate-edit").disabled = !draft || checking || $("generate").disabled;
  $("restore").disabled = !envelope?.result.editable_draft || checking || $("generate").disabled;
  $("download-script").disabled = !approved || checking || $("generate").disabled;
  $("download-run").disabled = !envelope;
}
function renderSources(facts) {
  $("sources").innerHTML = facts.length ? facts.map(f => `<article class="source-card"><div><strong>${escapeHTML(f.fact_id)}</strong><span>${escapeHTML(f.version_date)}</span></div><p>产品事实：${escapeHTML(f.text)}</p><blockquote>${escapeHTML(f.source_text)}</blockquote><small>素材 ${escapeHTML(f.material_id)} · SHA256 ${escapeHTML(f.source_hash.slice(0,16))}…</small></article>`).join("") : '<div class="detail-placeholder">本轮未读取到可核验的产品事实。</div>';
}
function renderRun(saved) {
  envelope = saved; draft = saved.result.editable_draft ? structuredClone(saved.result.editable_draft) : null;
  manual = null; editing = false; approved = saved.result.status === "completed"; editVersion++;
  const r = saved.result;
  status(r.status, r.execution_mode === "mock" ? "离线 Mock · 原始运行结果" : "真实模型 · 原始运行结果");
  $("metric-duration").textContent = r.duration_check?.estimated_total_seconds ?? "—";
  $("metric-target").textContent = `/ ${r.request.target_seconds ?? "?"} 秒`;
  $("duration-path").textContent = r.duration_history.length ? r.duration_history.map(x => x.estimated_total_seconds ?? "失败").join(" → ") + " 秒" : "尚无有效时长检查";
  $("metric-revisions").textContent = r.revisions.length;
  $("metric-sources").textContent = new Set(r.fact_inventory.map(x => x.material_id)).size;
  $("editor-label").textContent = r.status === "completed" ? "02 / 当前版本检查通过" : "02 / 未通过草稿";
  $("edit-notice").hidden = r.status === "completed" || !draft;
  $("edit-notice").textContent = "这是未完成草稿，不能作为通过脚本下载；可修订后单独校验。";
  $("validation-result").replaceChildren();
  renderEditor(); renderSources(r.fact_inventory);
  $("trace-count").textContent = r.trace.length;
  $("panel-trace").innerHTML = r.trace.map(s => `<details class="trace-item"><summary><span class="trace-number">${s.step}</span>${escapeHTML(toolNames[s.tool] || s.event)}<span class="pill ${s.observation?.ok ? "succeeded" : "failed"}">${s.observation?.ok ? "已返回" : "失败"}</span></summary><div class="trace-body"><b>动作依据</b><p>${escapeHTML(s.decision_basis || s.error)}</p><b>参数</b><pre>${escapeHTML(pretty(s.arguments))}</pre><b>返回摘要</b><pre>${escapeHTML(pretty(s.observation_summary))}</pre><b>实际工具返回</b><pre>${escapeHTML(pretty(s.observation))}</pre><b>下一步</b><p>${escapeHTML(s.next_action)}</p></div></details>`).join("");
  $("panel-gaps").innerHTML = `<p class="outcome-description">${escapeHTML(r.message)}</p>` + (r.gaps.length ? r.gaps.map(g => `<p class="gap-item">${escapeHTML(g)}</p>`).join("") : '<p class="outcome-description">当前原始脚本无待处理缺口。</p>') + `<pre class="risks-json">${escapeHTML(pretty({tool_errors:r.tool_errors,risks:r.rule_check?.risks || []}))}</pre>`;
  $("raw-json").textContent = pretty(saved); updateButtons();
}
async function generate(event) {
  event?.preventDefault(); error("");
  $("generate").disabled = true; $("result-area").setAttribute("aria-busy","true"); updateButtons();
  $("generate").firstElementChild.textContent = "正在生成与核验…";
  try {
    const request = {request_id:"web-" + Date.now(),theme:$("theme").value.trim() || null,audience:$("audience").value.trim() || null,platform:$("platform").value.trim() || null,target_seconds:$("target").value === "" ? null : Number($("target").value),style:$("style").value.trim() || null};
    renderRun(await api("/api/run", {request,case:$("case").value,max_steps:Number($("max-steps").value)}));
    await history();
  } catch (e) { error(e.message); }
  finally { $("generate").disabled = false; $("generate").firstElementChild.textContent = "生成并检查脚本"; $("result-area").setAttribute("aria-busy","false"); updateButtons(); }
}
async function checkEdit() {
  error(""); checking = true; updateButtons();
  const version = editVersion;
  const payload = {run_id:envelope.run_id,script:structuredClone(draft)};
  try {
    const checked = await api("/api/check_edit", payload);
    if (version !== editVersion) return; // an in-flight check cannot approve subsequent typing
    manual = checked; approved = checked.validation.approved; editing = false;
    const v = checked.validation;
    status(v.status, "人工编辑校验 · 独立于原始 Agent 运行");
    $("metric-duration").textContent = v.duration_check.estimated_total_seconds ?? "无效";
    $("editor-label").textContent = approved ? "02 / 编辑版本校验通过" : "02 / 编辑版本未通过";
    $("edit-notice").hidden = approved;
    $("edit-notice").textContent = "编辑未通过，不能下载为通过脚本。请修正下列问题后重新检查。";
    const reasons = [...(v.rule_check.risks || []).map(r => (riskLabels[r.code] || "脚本格式或内容需要修正") + (r.shot_id ? " · " + r.shot_id : "") + (r.term ? " · " + r.term : "")), ...(!v.duration_check.within_limit ? [v.duration_check.error ? "脚本格式无效，无法估算时长" : `预计超出 ${v.duration_check.over_seconds} 秒`] : [])];
    $("validation-result").innerHTML = reasons.map(text => `<p class="gap-item">${escapeHTML(text)}</p>`).join("");
    $("raw-json").textContent = pretty({original_run:envelope,manual_edit:checked});
    renderEditor();
  } catch (e) { error(e.message); approved = false; }
  finally { checking = false; updateButtons(); }
}
function download(value, name) {
  const url = URL.createObjectURL(new Blob([pretty(value) + "\n"], {type:"application/json;charset=utf-8"}));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
}
async function history() {
  const saved = await api("/api/history");
  $("history-list").innerHTML = saved.runs.length ? saved.runs.map(r => `<button class="history-row" data-run="${r.run_id}"><span class="theme">${escapeHTML(r.theme || "未填写主题")}</span><span class="pill ${r.status}">${escapeHTML(labels[r.status])}</span><span>${r.estimated_seconds ?? "—"} 秒</span><span class="date">${escapeHTML(new Date(r.generated_at).toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit"}))}</span><span class="arrow">↗</span></button>`).join("") : '<div class="detail-placeholder">还没有创作记录。</div>';
  document.querySelectorAll("[data-run]").forEach(button => button.addEventListener("click", async () => {
    try { const saved = await api("/api/results/" + button.dataset.run); selectCase(saved.case); for (const k of ["theme","audience","platform","style"]) $(k).value = saved.result.request[k] ?? ""; $("target").value = saved.result.request.target_seconds ?? ""; $("max-steps").value = saved.result.max_steps; renderRun(saved); $("result-area").scrollIntoView({behavior:"smooth"}); } catch(e) { error(e.message); }
  }));
}
async function materials() {
  try {
    const data = await api("/api/catalog?case=" + encodeURIComponent($("case").value));
    $("materials-body").innerHTML = data.materials.map(m => `<div class="source-card"><div><strong>${escapeHTML(m.id)} · ${escapeHTML(m.title)}</strong><span>${escapeHTML(m.version_date)}</span></div><blockquote>${escapeHTML(m.source_text)}</blockquote><p>${escapeHTML(m.facts.map(f => f.id + ": " + f.text).join("；"))}</p></div>`).join("") + `<h3>品牌与时长规则</h3><p>禁用词：${escapeHTML(data.rules.prohibited_terms.join("、"))}</p><p>每秒 ${data.rules.characters_per_second} 字；每镜至少 ${data.rules.min_scene_seconds} 秒，加额外停留时间。旁白、字幕同时显示，按较长者计算。</p><h3>可通过的中性文案</h3><p>新自由文案需人工审查，当前检查器只自动放行以下模板及素材事实原文。</p><ul>${Object.values(data.neutral_copy).map(x => `<li>${escapeHTML(x)}</li>`).join("")}</ul>`;
    $("materials-dialog").showModal();
  } catch(e) { error(e.message); }
}
async function init() {
  try {
    config = await api("/api/config");
    $("case").innerHTML = config.cases.map(c => `<option value="${c.id}">${escapeHTML(c.label)}</option>`).join("");
    selectCase(config.default_case);
    $("mode-tag").textContent = config.model === "mock" ? "离线 Mock" : "DeepSeek";
    if(config.model !== "mock") $("mode-notice").textContent = "真实模型选择工具动作；素材与模板为合成数据，时长为估算。";
    $("script-form").addEventListener("submit", generate);
    $("case").addEventListener("change", () => selectCase($("case").value));
    document.querySelectorAll("[data-case]").forEach(b => b.addEventListener("click", () => selectCase(b.dataset.case)));
    $("validate-edit").addEventListener("click", checkEdit);
    $("restore").addEventListener("click", () => renderRun(envelope));
    $("download-script").addEventListener("click", () => { if(approved && draft) download(manual ? {script:draft,validation:manual.validation} : envelope.result.final_script,"approved-video-script.json"); });
    $("download-run").addEventListener("click", () => { if(envelope) download(manual ? {original_run:envelope,manual_edit:manual} : envelope,"video-script-run.json"); });
    $("refresh-history").addEventListener("click", () => history().catch(e => error(e.message)));
    $("view-materials").addEventListener("click", materials);
    $("close-materials").addEventListener("click", () => $("materials-dialog").close());
    $("nav-work").addEventListener("click", () => $("work-area").scrollIntoView({behavior:"smooth"}));
    $("nav-history").addEventListener("click", () => $("history-area").scrollIntoView({behavior:"smooth"}));
    document.querySelectorAll("[data-tab]").forEach(b => b.addEventListener("click", () => { document.querySelectorAll("[data-tab]").forEach(x => {x.classList.toggle("active",x===b);x.setAttribute("aria-selected",String(x===b));$("panel-"+x.dataset.tab).hidden=x!==b;}); }));
    await history();
  } catch(e) { $("mode-tag").textContent = "连接失败"; error(e.message); }
}
init();
