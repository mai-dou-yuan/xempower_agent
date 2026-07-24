const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  sessionId: localStorage.getItem("boxingJudgeSession"),
  session: null,
  progressTimer: null,
};

const statusNames = {
  ANALYZING: "分析数据中",
  AWAITING_SUPPLEMENT_CHOICE: "等待选择",
  AWAITING_USER_INPUT: "等待补充",
  SUPPLEMENT_SKIPPED: "已跳过补充",
  AWAITING_CONFIRMATION: "等待确认",
  RETRIEVING_RULES: "检索规则中",
  SCORING: "评判中",
  REPORTING: "生成报告中",
  COMPLETE: "分析完成",
  LLM_UNAVAILABLE: "模型暂不可用",
};

const issueNames = {
  round_mapping: "回合映射",
  effective_offense_quality: "有效进攻质量",
  official_rulings: "正式裁定",
  coverage: "数据覆盖范围",
};

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 2600);
}

function setView(name) {
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `${name}View`));
  const order = ["upload", "context", "rules", "report"];
  const current = name === "loading" ? 2 : Math.max(0, order.indexOf(name));
  $$("#steps li").forEach((step, index) => {
    step.classList.toggle("active", index === current);
    step.classList.toggle("done", index < current);
  });
  if (window.innerWidth < 850) $(".workspace").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const error = payload?.error || {};
    throw new Error(error.message || `请求失败（HTTP ${response.status}）`);
  }
  return payload;
}

function setLoading(title, copy, showProgress = false) {
  $("#loadingTitle").textContent = title;
  $("#loadingCopy").textContent = copy;
  $("#liveProgress").classList.toggle("hidden", !showProgress);
  if (!showProgress) $("#toolTimeline").innerHTML = "";
  setView("loading");
}

function renderToolProgress(events = []) {
  const timeline = $("#toolTimeline");
  if (!events.length) {
    timeline.innerHTML = '<div class="tool-event running"><span class="event-icon">···</span><div class="event-main"><strong>等待任务启动</strong><small>后端即将开始处理。</small></div></div>';
    return;
  }
  const icons = { running: "···", completed: "✓", failed: "!", skipped: "—" };
  timeline.innerHTML = events.map((event) => `<div class="tool-event ${escapeHtml(event.status)}">
    <span class="event-icon">${icons[event.status] || "·"}</span>
    <div class="event-main"><strong>${escapeHtml(event.title)}</strong><small>${escapeHtml(event.message)}</small></div>
    <span class="event-tool">${escapeHtml(event.tool)}</span>
  </div>`).join("");
  const latest = events[events.length - 1];
  if (latest?.status === "running") {
    $("#loadingTitle").textContent = latest.title;
    $("#loadingCopy").textContent = latest.message;
  }
  timeline.scrollTop = timeline.scrollHeight;
}

function stopProgressPolling() {
  if (state.progressTimer) clearInterval(state.progressTimer);
  state.progressTimer = null;
}

async function refreshProgress() {
  if (!state.sessionId) return;
  try {
    const result = await api(`/sessions/${state.sessionId}/progress`);
    renderToolProgress(result.progress);
  } catch (_) {
    // The main confirmation request owns user-facing errors; polling stays quiet.
  }
}

function startProgressPolling() {
  stopProgressPolling();
  renderToolProgress(state.session?.progress_events || []);
  refreshProgress();
  state.progressTimer = setInterval(refreshProgress, 700);
}

function saveSession(session) {
  state.session = session;
  state.sessionId = session.session_id;
  localStorage.setItem("boxingJudgeSession", state.sessionId);
}

function renderIssues(items = []) {
  if (!items.length) return '<p class="context-lead">数据结构完整，可以继续进行规则检索与分析。</p>';
  return `<p class="context-lead">为了避免把预测数量误当作正式得分，以下信息仍需确认。你可以补充事实，也可以按现有证据继续。</p>
    <div class="issue-list">${items.map((item, index) => `
      <div class="issue"><span>${String(index + 1).padStart(2, "0")}</span><div>
        <strong>${escapeHtml(issueNames[item.key] || item.key)}</strong>
        <p>${escapeHtml(item.impact)}</p>
      </div></div>`).join("")}</div>`;
}

function actionButton(action, title, copy, accent = false, danger = false) {
  return `<button class="action-btn${accent ? " accent" : ""}${danger ? " danger" : ""}" data-action="${action}" type="button"><strong>${title}</strong><small>${copy}</small></button>`;
}

function renderSupplementProgress(session) {
  const hasConfirmed = Boolean(session.supplements?.length);
  const isChoosing = session.status === "AWAITING_SUPPLEMENT_CHOICE";
  const isAssumption = session.status === "AWAITING_CONFIRMATION" && !session.pending_supplements?.length;
  const active = isChoosing ? 0 : isAssumption ? 2 : 1;
  const labels = ["选择补充方式", "录入并确认事实", "完成补充，确认映射"];
  $("#contextProgress").innerHTML = labels.map((label, index) =>
    `<div class="context-progress-step${index === active ? " active" : ""}${index < active ? " done" : ""}">${label}</div>`
  ).join("");

  const panel = $("#confirmedSupplements");
  if (!hasConfirmed) {
    panel.innerHTML = "";
    return;
  }
  panel.innerHTML = `<div class="confirmed-panel"><header><strong>已确认补充信息 · 自动保存</strong><span>${session.supplements.length}</span></header>
    <ul class="confirmed-list">${session.supplements.map((item) => {
      const value = typeof item.value === "object" ? JSON.stringify(item.value) : item.value;
      return `<li><span class="confirmed-check">✓</span><div><strong>${escapeHtml(issueNames[item.metric] || item.metric)}</strong><small>${escapeHtml(value)}</small></div></li>`;
    }).join("")}</ul></div>`;
}

function renderContext(session, extra = {}) {
  saveSession(session);
  setView("context");
  $("#sessionStatus").textContent = statusNames[session.status] || session.status;
  $("#sessionId").textContent = session.session_id;
  renderSupplementProgress(session);
  const content = $("#contextContent");
  const actions = $("#actionArea");
  actions.innerHTML = "";

  if (session.status === "AWAITING_SUPPLEMENT_CHOICE") {
    content.innerHTML = renderIssues(session.missing_context?.items || []);
    actions.innerHTML = actionButton("add_supplement", "补充比赛信息", "提供回合、击倒、扣分等事实", true)
      + actionButton("skip_supplement", "按现有证据继续", "系统会提出最小映射假设");
  } else if (session.status === "AWAITING_USER_INPUT") {
    const questions = extra.questions || session.missing_context?.questions || [];
    const savedNotice = session.supplements?.length
      ? `<p class="saved-notice">上方 ${session.supplements.length} 条信息已经保存，无需重复输入。你可以继续补充其他事实，或点击“完成补充，进入下一步”。</p>`
      : "";
    content.innerHTML = `${savedNotice}<p class="context-lead">请用自然语言补充你确认的信息。系统会先展示结构化理解，只有确认后才会用于分析。</p>
      <div class="issue-list">${questions.slice(0, 3).map((q, i) => `<div class="issue"><span>Q${i + 1}</span><div><p>${escapeHtml(q)}</p></div></div>`).join("")}</div>`;
    actions.innerHTML = `<div class="supplement-box"><textarea id="supplementText" placeholder="例如：第 1 回合红方干净重拳明显更多；双方没有正式扣分。"></textarea>
      <div class="hint-chips"><span>回合与视频映射</span><span>干净命中与效果</span><span>正式击倒或扣分</span></div>
      <button class="primary-btn" data-action="send_message" type="button"><span>解析补充信息</span><b>→</b></button></div>
      ${actionButton("skip_supplement", session.supplements?.length ? "完成补充，进入下一步" : "不再补充，按现有证据继续", session.supplements?.length ? "保留以上已确认信息，并确认回合映射" : "未提供信息将保持未知")}`;
  } else if (session.status === "AWAITING_CONFIRMATION" && session.pending_supplements?.length) {
    content.innerHTML = `<div class="parsed-card"><h3>请核对系统的结构化理解</h3>${session.pending_supplements.map((item) => `
      <div class="parsed-item"><code>${escapeHtml(item.metric)}</code><span>${escapeHtml(typeof item.value === "object" ? JSON.stringify(item.value) : item.value)}</span></div>`).join("")}</div>`;
    if (extra.conflicts?.length) content.innerHTML += `<div class="report-error">发现 ${extra.conflicts.length} 项信息与已确认内容冲突，请确认是否采用新内容。</div>`;
    actions.innerHTML = actionButton("confirm_supplements", "确认并用于分析", "写入本次会话的事实记录", true)
      + actionButton("edit_supplement", "返回修改", "重新输入这段补充信息");
  } else if (session.status === "AWAITING_CONFIRMATION" && session.assumptions?.length) {
    const assumption = session.assumptions[0];
    const mapping = assumption?.value && typeof assumption.value === "object"
      ? Object.entries(assumption.value).map(([video, round]) => `${escapeHtml(video)} → 第 ${round} 回合`).join("<br>")
      : escapeHtml(assumption?.raw_user_text || "按视频排序映射为回合");
    content.innerHTML = `<p class="context-lead">生成唯一逐回合估算前，需要你确认以下最小假设：</p>
      <div class="parsed-card"><h3>${escapeHtml(assumption?.raw_user_text || "视频顺序即回合顺序")}</h3><div class="parsed-item"><code>mapping</code><span>${mapping}</span></div></div>`;
    actions.innerHTML = actionButton("confirm_assumptions", "确认假设并生成主估算", "将调用规则检索与 DeepSeek", true)
      + actionButton("reject_assumptions", "拒绝假设，生成条件报告", "不会虚构唯一逐回合比分", false, true);
  } else if (session.status === "COMPLETE" || session.status === "LLM_UNAVAILABLE") {
    if (session.report) renderReport(session.report, session);
    else loadReport();
  } else {
    content.innerHTML = `<p class="context-lead">当前状态：${escapeHtml(statusNames[session.status] || session.status)}</p>`;
  }
}

async function sendAction(action) {
  if (action === "edit_supplement") {
    state.session.status = "AWAITING_USER_INPUT";
    state.session.pending_supplements = [];
    renderContext(state.session);
    return;
  }
  if (action === "send_message") {
    const message = $("#supplementText")?.value.trim();
    if (!message) return toast("请先填写补充信息");
    setLoading("正在解析补充信息", "系统会将自然语言转换为可确认的结构化事实。");
    try {
      const result = await api(`/sessions/${state.sessionId}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }),
      });
      renderContext(result.session, result);
    } catch (error) { renderContext(state.session); toast(error.message); }
    return;
  }

  const finalizing = ["confirm_assumptions", "reject_assumptions", "confirm_supplements"].includes(action);
  if (finalizing) {
    setLoading("正在完成评判分析", "准备检索规则证据、调用模型并生成可复核报告。", true);
    startProgressPolling();
  }
  try {
    const result = await api(`/sessions/${state.sessionId}/confirm`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }),
    });
    if (result.session?.report) renderReport(result.session.report, result.session);
    else renderContext(result.session, result);
  } catch (error) {
    if (state.session) renderContext(state.session);
    toast(error.message);
  } finally {
    if (finalizing) stopProgressPolling();
  }
}

function inlineMarkdown(text) {
  return text.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderMarkdown(markdown = "") {
  const lines = escapeHtml(markdown).split("\n");
  let html = "", inList = false, inTable = false;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (line.startsWith("|")) {
      if (/^\|[\s:|-]+\|$/.test(line)) continue;
      const cells = line.slice(1, -1).split("|").map((x) => inlineMarkdown(x.trim()));
      if (!inTable) { html += `<table class="markdown-table"><thead><tr>${cells.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`; inTable = true; }
      else html += `<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
      continue;
    } else if (inTable) { html += "</tbody></table>"; inTable = false; }
    if (line.startsWith("- ")) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inlineMarkdown(line.slice(2))}</li>`;
      continue;
    } else if (inList) { html += "</ul>"; inList = false; }
    if (line.startsWith("# ")) html += `<h1>${inlineMarkdown(line.slice(2))}</h1>`;
    else if (line.startsWith("## ")) html += `<h2>${inlineMarkdown(line.slice(3))}</h2>`;
    else if (line.startsWith("&gt; ")) html += `<blockquote>${inlineMarkdown(line.slice(5))}</blockquote>`;
    else if (line.trim()) html += `<p>${inlineMarkdown(line)}</p>`;
  }
  if (inList) html += "</ul>";
  if (inTable) html += "</tbody></table>";
  return html;
}

function renderReport(report, session = state.session || {}) {
  saveSession({ ...session, session_id: report.session_id || state.sessionId, report });
  setView("report");
  const score = report.scorecard || {};
  const complete = Boolean(score.complete);
  const rounds = report.round_assessments || [];
  const error = session.last_error ? `<div class="report-error">模型服务异常：${escapeHtml(session.last_error.message)}。以下报告保留已完成的确定性分析。</div>` : "";
  $("#reportContent").innerHTML = `${error}
    <div class="score-hero">
      <div class="fighter red"><small>RED CORNER</small><strong>${complete ? escapeHtml(score.red_total) : "—"}</strong></div>
      <div class="score-divider"><b>${complete ? "FINAL" : "PENDING"}</b><span></span><small>${rounds.length} RDS</small></div>
      <div class="fighter blue"><small>BLUE CORNER</small><strong>${complete ? escapeHtml(score.blue_total) : "—"}</strong></div>
    </div>
    <div class="report-flags"><span class="valid">${escapeHtml(report.status)}</span><span>非官方估算</span><span>${escapeHtml(report.score_kind)}</span><span>${report.rule_evidence?.length || 0} 条规则证据</span></div>
    ${rounds.length ? `<div class="report-section"><h3>逐回合判断</h3><div class="round-grid">${rounds.map((round) => `
      <article class="round-card"><header><span>ROUND ${round.round}</span><span class="winner-${escapeHtml(round.winner)}">${escapeHtml(round.winner).toUpperCase()}</span></header><p>${escapeHtml(round.reason)}</p></article>`).join("")}</div></div>` : ""}
    <div class="report-section"><h3>完整分析</h3><div class="markdown">${renderMarkdown(report.report_markdown)}</div></div>`;
}

async function loadReport() {
  setLoading("正在恢复分析报告", "从本地会话存储中读取报告。");
  try {
    const report = await api(`/sessions/${state.sessionId}/report`);
    renderReport(report, state.session || {});
  } catch (error) { setView("upload"); toast(error.message); }
}

async function resumeSession() {
  if (!state.sessionId) return;
  setLoading("正在恢复会话", "读取上次分析的状态与结果。");
  try {
    const result = await api(`/sessions/${state.sessionId}`);
    if (result.session.report) renderReport(result.session.report, result.session);
    else renderContext(result.session);
  } catch (error) {
    localStorage.removeItem("boxingJudgeSession"); state.sessionId = null; setView("upload"); toast("上次会话已不可用");
  }
}

$("#uploadForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("#csvFile").files[0];
  if (!file) return toast("请选择 CSV 文件");
  const button = $("#submitUpload");
  button.disabled = true;
  setLoading("正在读取赛事数据", "校验 CSV、汇总预测事件并分析缺失的比赛上下文。");
  const form = new FormData();
  form.append("csv", file);
  const question = $("#question").value.trim();
  if (question) form.append("question", question);
  try {
    const result = await api("/sessions", { method: "POST", body: form });
    renderContext(result.session);
  } catch (error) { setView("upload"); toast(error.message); }
  finally { button.disabled = false; }
});

const dropzone = $("#dropzone"), fileInput = $("#csvFile");
function showFile(file) {
  if (!file) return;
  $("#fileTitle").textContent = file.name;
  $("#fileMeta").textContent = `${(file.size / 1024).toFixed(1)} KB · 已准备上传`;
  dropzone.classList.add("has-file");
}
fileInput.addEventListener("change", () => showFile(fileInput.files[0]));
["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("dragover"); }));
["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove("dragover"); }));
dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (!file || !file.name.toLowerCase().endsWith(".csv")) return toast("请选择 .csv 文件");
  const transfer = new DataTransfer(); transfer.items.add(file); fileInput.files = transfer.files; showFile(file);
});

$("#actionArea").addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");
  if (button) sendAction(button.dataset.action);
});
$("#copySession").addEventListener("click", async () => { await navigator.clipboard.writeText(state.sessionId || ""); toast("会话 ID 已复制"); });
$("#newAnalysis").addEventListener("click", () => { state.session = null; setView("upload"); });
$("#resumeButton").addEventListener("click", resumeSession);

async function checkHealth() {
  try {
    await api("/health"); $("#healthDot").className = "pulse online"; $("#healthText").textContent = "服务在线";
  } catch (_) { $("#healthDot").className = "pulse offline"; $("#healthText").textContent = "连接异常"; }
}

checkHealth();
if (state.sessionId) $("#resumeButton").classList.remove("hidden");
