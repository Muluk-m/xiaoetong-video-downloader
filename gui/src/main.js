// ============ API ============
const API_BASE = "http://127.0.0.1:19528";

// ============ State ============
let currentTaskId = null;
let pollTimer = null;
let logPollTimer = null;
let logLastTimestamp = 0;
let videos = [];
let selectedCount = 0;

// ============ Tauri invoke helper ============
let invoke = null;
try {
  invoke = window.__TAURI__?.core?.invoke;
} catch (e) { /* not in Tauri */ }

// ============ Error Classes ============
class BackendUnreachableError extends Error {
  constructor(originalMessage) {
    super("后端服务无法连接");
    this.name = "BackendUnreachableError";
    this.originalMessage = originalMessage;
  }
}

// ============ Helpers ============
async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  } catch (e) {
    if (e.message && (e.message.includes("Load failed") || e.message.includes("Failed to fetch") || e.message.includes("NetworkError"))) {
      throw new BackendUnreachableError(e.message);
    }
    throw e;
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);

function showMessage(el, text, type = "info") {
  el.textContent = text;
  el.className = `message show ${type}`;
  setTimeout(() => el.classList.remove("show"), 4000);
}

function setStepDone(stepId) {
  const dot = $(`#${stepId}`);
  dot.classList.add("done");
  dot.textContent = "\u2713";
}

function handleError(e, fallbackEl, prefix = "") {
  if (e instanceof BackendUnreachableError) {
    updateConnectionBanner("error", e.message);
  }
  if (fallbackEl) {
    const msg = prefix ? `${prefix}: ${e.message}` : e.message;
    if (fallbackEl.classList.contains("message")) {
      showMessage(fallbackEl, msg, "error");
    } else {
      fallbackEl.textContent = msg;
      fallbackEl.style.color = "var(--red)";
    }
  }
}

// ============ Connection Banner ============
function updateConnectionBanner(status, detail) {
  const banner = $("#connection-banner");
  const msg = $("#conn-banner-msg");

  if (status === "hidden" || status === "running") {
    banner.style.display = "none";
    return;
  }

  banner.style.display = "flex";
  banner.className = "conn-banner";

  if (status === "starting") {
    banner.classList.add("conn-banner--starting");
    msg.textContent = detail || "后端服务启动中...";
  } else if (status === "error" || status === "failed") {
    banner.classList.add("conn-banner--error");
    msg.textContent = detail || "后端服务连接失败";
  }
}

// ============ Navigation ============
$$(".rail-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    $$(".rail-btn").forEach(b => b.classList.remove("active"));
    $$(".panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    $(`#tab-${tab}`).classList.add("active");

    // Start/stop log polling based on tab
    if (tab === "logs") {
      startLogPolling();
    } else {
      stopLogPolling();
    }
  });
});

// ============ Server check ============
async function checkServer() {
  const dot = $("#server-status");
  try {
    await api("/api/config");
    dot.className = "conn-dot conn-ok";
    dot.title = "已连接";
    return true;
  } catch (e) {
    if (e instanceof BackendUnreachableError) {
      dot.className = "conn-dot conn-error";
      dot.title = "未连接";
    } else {
      dot.className = "conn-dot conn-error";
      dot.title = "连接异常";
    }
    return false;
  }
}

async function waitForServer() {
  // First check Tauri-side backend status
  if (invoke) {
    try {
      const st = await invoke("get_backend_status");
      if (st.status === "not_found") {
        updateConnectionBanner("error", "未找到后端程序: " + (st.error || ""));
        return;
      }
      if (st.status === "failed") {
        updateConnectionBanner("error", "后端启动失败: " + (st.error || ""));
        return;
      }
    } catch (e) {
      // Not in Tauri, proceed with HTTP polling
    }
  }

  updateConnectionBanner("starting", "后端服务启动中，请稍候...");

  for (let i = 0; i < 30; i++) {
    // Check Tauri status each iteration
    if (invoke) {
      try {
        const st = await invoke("get_backend_status");
        if (st.status === "failed" || st.status === "not_found") {
          updateConnectionBanner("error", "后端启动失败: " + (st.error || "未知错误"));
          $("#server-status").className = "conn-dot conn-error";
          return;
        }
      } catch (e) { /* ignore */ }
    }

    if (await checkServer()) {
      updateConnectionBanner("hidden");
      loadConfig();
      return;
    }
    await new Promise(r => setTimeout(r, 1000));
  }

  updateConnectionBanner("error", "后端服务在 30 秒内未能启动，请查看日志");
  $("#server-status").className = "conn-dot conn-error";
}

// ============ Config ============
async function loadConfig() {
  try {
    const data = await api("/api/config");
    if (data.success && data.config) {
      const c = data.config;
      $("#input-cookie").value = c.cookie || "";
      $("#input-app-id").value = c.app_id || "";
      $("#input-product-id").value = c.product_id || "";
      $("#input-download-dir").value = c.download_dir || "download";
      $("#input-max-workers").value = c.max_workers || 5;

      if (c.app_id && c.product_id) {
        $("#parsed-app-id").textContent = c.app_id;
        $("#parsed-product-id").textContent = c.product_id;
        $("#parsed-info").style.display = "flex";
        setStepDone("step2-dot");
      }

      if (c.cookie) {
        setStepDone("step1-dot");
        $("#cookie-hint").textContent = "已有登录信息";
        $("#cookie-hint").style.color = "var(--green)";
      }
    }
  } catch (e) {
    handleError(e);
  }
}

// ============ Step 1: Auto Cookie ============
$("#btn-auto-cookie").addEventListener("click", async () => {
  const btn = $("#btn-auto-cookie");
  const hint = $("#cookie-hint");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>正在读取浏览器登录信息...';

  try {
    const data = await api("/api/cookies");
    if (data.success) {
      $("#input-cookie").value = data.cookie;
      hint.textContent = "登录信息同步成功";
      hint.style.color = "var(--green)";
      setStepDone("step1-dot");
      autoSaveConfig();
    } else {
      hint.textContent = "未找到登录信息，请先用 Chrome 打开小鹅通并登录";
      hint.style.color = "var(--red)";
    }
  } catch (e) {
    handleError(e, hint, "读取失败");
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16"><path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd"/></svg>一键同步 Chrome 登录';
  }
});

// ============ Step 2: Parse URL ============
$("#btn-parse-url").addEventListener("click", parseUrl);
$("#input-course-url").addEventListener("keydown", (e) => {
  if (e.key === "Enter") parseUrl();
});

async function parseUrl() {
  const url = $("#input-course-url").value.trim();
  const hint = $("#url-hint");
  if (!url) {
    hint.textContent = "请粘贴课程链接";
    hint.style.color = "var(--red)";
    return;
  }

  try {
    const data = await api("/api/parse-url", {
      method: "POST",
      body: JSON.stringify({ url }),
    });

    if (data.success) {
      $("#input-app-id").value = data.app_id;
      $("#input-product-id").value = data.product_id;
      $("#parsed-app-id").textContent = data.app_id;
      $("#parsed-product-id").textContent = data.product_id;
      $("#parsed-info").style.display = "flex";
      hint.textContent = "解析成功";
      hint.style.color = "var(--green)";
      setStepDone("step2-dot");
      autoSaveConfig();
    } else {
      hint.textContent = data.message || "无法识别链接，请确认是小鹅通课程页面的链接";
      hint.style.color = "var(--red)";
    }
  } catch (e) {
    handleError(e, hint, "解析失败");
  }
}

// ============ Browse Directory ============
$("#btn-browse-dir").addEventListener("click", async () => {
  const hint = $("#dir-hint");
  try {
    const data = await api("/api/browse-dir");
    if (data.success) {
      $("#input-download-dir").value = data.path;
      hint.textContent = "已选择: " + data.path;
      hint.style.color = "var(--green)";
      autoSaveConfig();
    }
  } catch (e) {
    handleError(e, hint, "选择失败");
  }
});

// ============ Auto-Save Config ============
let _saveTimer = null;

function _gatherConfig() {
  return {
    cookie: $("#input-cookie").value.trim(),
    app_id: $("#input-app-id").value.trim(),
    product_id: $("#input-product-id").value.trim(),
    download_dir: $("#input-download-dir").value.trim() || "download",
    max_workers: parseInt($("#input-max-workers").value) || 5,
  };
}

async function autoSaveConfig() {
  const msg = $("#config-message");
  const config = _gatherConfig();

  try {
    const data = await api("/api/config", { method: "POST", body: JSON.stringify(config) });
    if (data.success) {
      showMessage(msg, "已自动保存", "success");
    }
  } catch (e) {
    handleError(e, msg, "自动保存失败");
  }
}

function scheduleAutoSave() {
  if (_saveTimer) clearTimeout(_saveTimer);
  _saveTimer = setTimeout(autoSaveConfig, 600);
}

// 监听所有配置输入框变化
["#input-cookie", "#input-app-id", "#input-product-id", "#input-download-dir", "#input-max-workers"].forEach(sel => {
  $(sel).addEventListener("input", scheduleAutoSave);
});

// ============ Check Env ============
$("#btn-check-env").addEventListener("click", async () => {
  const btn = $("#btn-check-env");
  const msg = $("#config-message");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>检查中';

  try {
    const data = await api("/api/check");
    showMessage(msg, data.message, data.success ? "success" : "error");
  } catch (e) {
    handleError(e, msg, "检查失败");
  } finally {
    btn.disabled = false;
    btn.textContent = "检查环境";
  }
});

// ============ Video List ============
$("#btn-refresh-videos").addEventListener("click", async () => {
  const btn = $("#btn-refresh-videos");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>加载中';

  try {
    const data = await api("/api/videos");
    if (data.success) {
      videos = data.videos;
      renderVideoList(videos);
      $("#video-count").textContent = `共 ${videos.length} 个视频`;
    } else {
      $("#video-list").innerHTML = `<div class="empty"><p>${data.message || "获取失败，请检查设置是否正确"}</p></div>`;
    }
  } catch (e) {
    if (e instanceof BackendUnreachableError) {
      updateConnectionBanner("error", e.message);
      $("#video-list").innerHTML = `<div class="empty"><p>后端服务无法连接，请查看日志</p></div>`;
    } else {
      $("#video-list").innerHTML = `<div class="empty"><p>获取失败: ${e.message}</p></div>`;
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "加载课程";
  }
});

function renderVideoList(list) {
  const container = $("#video-list");
  if (!list.length) {
    container.innerHTML = '<div class="empty"><p>该课程下没有找到视频</p></div>';
    return;
  }

  container.innerHTML = list.map((v, i) => {
    const title = v.resource_title || "未知标题";
    const id = v.resource_id || "";
    const date = v.start_at || "";
    const dlStatus = v.dl_status || "none";

    let statusHtml = "";
    let revealBtnHtml = "";
    if (dlStatus === "done") {
      statusHtml = '<span class="dl-badge dl-badge--done">已下载</span>';
      revealBtnHtml = `<button class="reveal-btn" data-title="${title.replace(/"/g, '&quot;')}" title="在 Finder 中显示"><svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"/></svg></button>`;
    } else if (dlStatus === "none") {
      statusHtml = '<span class="dl-badge dl-badge--none">未下载</span>';
    } else {
      statusHtml = `<span class="dl-badge dl-badge--partial">下载中 ${dlStatus}</span>`;
    }

    return `
      <div class="video-item${dlStatus === 'done' ? ' video-item--done' : ''}" data-id="${id}">
        <input type="checkbox" class="video-checkbox" value="${id}" />
        <span class="vi-index">${i + 1}</span>
        <div class="vi-info">
          <div class="vi-title" title="${title}">${title}</div>
          <div class="vi-meta">${date}</div>
        </div>
        <div class="vi-status">
          ${revealBtnHtml}
          ${statusHtml}
        </div>
      </div>`;
  }).join("");

  container.querySelectorAll(".video-item").forEach(item => {
    item.addEventListener("click", (e) => {
      if (e.target.type === "checkbox") { updateSelectedCount(); return; }
      if (e.target.closest(".reveal-btn")) return;
      const cb = item.querySelector(".video-checkbox");
      cb.checked = !cb.checked;
      updateSelectedCount();
    });
  });

  container.querySelectorAll(".reveal-btn").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const title = btn.dataset.title;
      try {
        const data = await api("/api/reveal-file", {
          method: "POST",
          body: JSON.stringify({ title }),
        });
        if (!data.success) {
          console.error("Reveal failed:", data.message);
        }
      } catch (err) {
        console.error("Reveal error:", err);
      }
    });
  });

  updateSelectedCount();
}

function updateSelectedCount() {
  selectedCount = $$(".video-checkbox:checked").length;
  const btn = $("#btn-download-selected");
  btn.disabled = selectedCount === 0;
  btn.textContent = selectedCount > 0 ? `下载选中 (${selectedCount})` : "下载选中";
}

// Select all
$("#cb-select-all").addEventListener("change", (e) => {
  $$(".video-checkbox").forEach(cb => cb.checked = e.target.checked);
  updateSelectedCount();
});

$("#btn-download-selected").addEventListener("click", async () => {
  const selected = Array.from($$(".video-checkbox:checked")).map(cb => cb.value);
  if (!selected.length) return;
  await startDownload(selected);
});

// ============ Download ============
async function startDownload(resourceIds = []) {
  // Switch to download tab
  $$(".rail-btn").forEach(b => b.classList.remove("active"));
  $$(".panel").forEach(p => p.classList.remove("active"));
  $$(".rail-btn")[2].classList.add("active");
  $("#tab-download").classList.add("active");

  // Reset UI
  $("#dl-progress-area").style.display = "block";
  $("#download-log").innerHTML = "";
  $("#download-results").style.display = "none";
  $("#btn-cancel-download").style.display = "inline-block";
  $("#dl-status-text").textContent = "启动中...";
  $("#dl-progress").textContent = "0/0";
  $("#dl-segments").textContent = "-";
  $("#dl-current").textContent = "-";
  $("#dl-bar").style.width = "0%";
  $("#dl-bar-pct").textContent = "0%";
  $("#seg-bar").style.width = "0%";
  $("#seg-bar-pct").textContent = "0%";
  $("#seg-track").style.display = "grid";

  try {
    const data = await api("/api/download", {
      method: "POST",
      body: JSON.stringify({ resource_ids: resourceIds, nocache: false, auto_transcode: true }),
    });

    if (data.success) {
      currentTaskId = data.task_id;
      startPolling(currentTaskId);
    } else {
      $("#dl-status-text").textContent = "启动失败";
      appendLog("error", data.message || "启动下载失败");
    }
  } catch (e) {
    $("#dl-status-text").textContent = "错误";
    if (e instanceof BackendUnreachableError) {
      updateConnectionBanner("error", e.message);
      appendLog("error", "后端服务无法连接");
    } else {
      appendLog("error", "启动下载失败: " + e.message);
    }
  }
}

function startPolling(taskId) {
  if (pollTimer) clearInterval(pollTimer);
  let lastLogLen = 0;

  pollTimer = setInterval(async () => {
    try {
      const task = await api(`/api/download/status/${taskId}`);

      const statusMap = { running: "下载中", completed: "全部完成", failed: "下载失败", cancelled: "已取消" };
      $("#dl-status-text").textContent = statusMap[task.status] || task.status;

      // Video-level progress
      if (task.total > 0) {
        $("#dl-progress").textContent = `${task.current}/${task.total}`;
        const pct = Math.round((task.current / task.total) * 100);
        $("#dl-bar").style.width = `${pct}%`;
        $("#dl-bar-pct").textContent = `${pct}%`;
      }

      if (task.current_title) {
        $("#dl-current").textContent = task.current_title;
      }

      // Segment-level progress
      if (task.segments_total > 0) {
        const segDl = task.segments_downloaded;
        const segTotal = task.segments_total;
        const segPct = Math.round((segDl / segTotal) * 100);
        $("#dl-segments").textContent = `${segDl}/${segTotal}`;
        $("#seg-bar").style.width = `${segPct}%`;
        $("#seg-bar-pct").textContent = `${segPct}%`;
      } else {
        $("#dl-segments").textContent = "...";
        $("#seg-bar").style.width = "0%";
        $("#seg-bar-pct").textContent = "";
      }

      // Append new logs
      if (task.progress && task.progress.length > lastLogLen) {
        task.progress.slice(lastLogLen).forEach(log => appendLog(log.type, log.message));
        lastLogLen = task.progress.length;
      }

      // Task finished
      if (["completed", "failed", "cancelled"].includes(task.status)) {
        clearInterval(pollTimer);
        pollTimer = null;
        currentTaskId = null;
        $("#btn-cancel-download").style.display = "none";
        $("#seg-track").style.display = "none";

        if (task.status === "completed") {
          $("#dl-bar").style.width = "100%";
          $("#dl-bar-pct").textContent = "100%";
          $("#dl-segments").textContent = "done";
        }

        showResults(task.results);
      }
    } catch (e) {
      if (e instanceof BackendUnreachableError) {
        clearInterval(pollTimer);
        pollTimer = null;
        updateConnectionBanner("error", e.message);
        appendLog("error", "后端服务断开连接");
      }
      console.error("Poll error:", e);
    }
  }, 800);
}

function appendLog(type, message) {
  const log = $("#download-log");
  const empty = log.querySelector(".dl-log-empty");
  if (empty) empty.remove();

  const line = document.createElement("div");
  line.className = `log-line ${type}`;
  line.textContent = message;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function showResults(results) {
  if (!results) return;
  const container = $("#download-results");
  const content = $("#results-content");
  container.style.display = "block";

  let html = "";
  if (results.success?.length) {
    html += results.success.map(r =>
      `<div class="result-item result-success"><span class="result-dot"></span>${r.title}</div>`
    ).join("");
  }
  if (results.failed?.length) {
    html += results.failed.map(r =>
      `<div class="result-item result-failed"><span class="result-dot"></span>${r.title} — ${r.message}</div>`
    ).join("");
  }
  content.innerHTML = html || '<p style="color:var(--text-3)">无结果</p>';
}

$("#btn-cancel-download").addEventListener("click", async () => {
  if (!currentTaskId) return;
  try {
    await api(`/api/download/cancel/${currentTaskId}`, { method: "POST" });
    appendLog("info", "正在取消...");
  } catch (e) {
    if (e instanceof BackendUnreachableError) {
      updateConnectionBanner("error", e.message);
    }
    appendLog("error", "取消失败: " + e.message);
  }
});

// ============ Backend Log Polling ============
function startLogPolling() {
  if (logPollTimer) return;
  fetchAndRenderLogs(); // immediate first fetch
  logPollTimer = setInterval(fetchAndRenderLogs, 1000);
}

function stopLogPolling() {
  if (logPollTimer) {
    clearInterval(logPollTimer);
    logPollTimer = null;
  }
}

async function fetchAndRenderLogs() {
  if (!invoke) return;

  try {
    const [statusResult, logsResult] = await Promise.all([
      invoke("get_backend_status"),
      invoke("get_backend_logs", { since: logLastTimestamp }),
    ]);

    // Update status display
    const statusMap = {
      starting: "启动中",
      running: "运行中",
      failed: "启动失败",
      not_found: "未找到",
    };
    const statusEl = $("#backend-status-display");
    statusEl.textContent = statusMap[statusResult.status] || statusResult.status;
    statusEl.style.color = statusResult.status === "running" ? "var(--green)" :
                           statusResult.status === "failed" || statusResult.status === "not_found" ? "var(--red)" :
                           "var(--accent)";

    // Update log count
    $("#backend-log-count").textContent = logsResult.total;

    // Update status subtitle
    const subtitle = $("#logs-status-text");
    if (statusResult.status === "failed" && statusResult.error) {
      subtitle.textContent = statusResult.error;
    } else {
      subtitle.textContent = `状态: ${statusMap[statusResult.status] || statusResult.status}`;
    }

    // Append new logs
    if (logsResult.logs.length > 0) {
      const output = $("#backend-log-output");
      const empty = output.querySelector(".dl-log-empty");
      if (empty) empty.remove();

      for (const entry of logsResult.logs) {
        const line = document.createElement("div");
        line.className = `log-line-${entry.stream}`;

        const ts = document.createElement("span");
        ts.className = "log-ts";
        const d = new Date(entry.timestamp);
        ts.textContent = `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}`;
        line.appendChild(ts);

        line.appendChild(document.createTextNode(entry.message));
        output.appendChild(line);

        if (entry.timestamp > logLastTimestamp) {
          logLastTimestamp = entry.timestamp;
        }
      }

      output.scrollTop = output.scrollHeight;
    }
  } catch (e) {
    console.error("Log poll error:", e);
  }
}

// ============ Banner action buttons ============
$("#btn-retry-conn").addEventListener("click", async () => {
  updateConnectionBanner("starting", "重新连接中...");
  await waitForServer();
});

$("#btn-restart-backend").addEventListener("click", async () => {
  if (!invoke) {
    updateConnectionBanner("error", "仅在桌面应用中支持重启后端");
    return;
  }
  updateConnectionBanner("starting", "正在重启后端...");
  try {
    await invoke("restart_backend");
    logLastTimestamp = 0;
    await waitForServer();
  } catch (e) {
    updateConnectionBanner("error", "重启失败: " + e.message);
  }
});

$("#btn-view-logs").addEventListener("click", () => {
  // Switch to logs tab
  $$(".rail-btn").forEach(b => b.classList.remove("active"));
  $$(".panel").forEach(p => p.classList.remove("active"));
  $$(".rail-btn")[3].classList.add("active");
  $("#tab-logs").classList.add("active");
  startLogPolling();
});

// ============ Logs panel buttons ============
$("#btn-clear-logs").addEventListener("click", () => {
  const output = $("#backend-log-output");
  output.innerHTML = '<p class="dl-log-empty">日志已清空</p>';
});

$("#btn-restart-backend-logs").addEventListener("click", async () => {
  if (!invoke) return;
  const btn = $("#btn-restart-backend-logs");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>重启中';

  try {
    await invoke("restart_backend");
    logLastTimestamp = 0;
    const output = $("#backend-log-output");
    output.innerHTML = '<p class="dl-log-empty">后端已重启，等待日志...</p>';
    // Also re-check connection
    await waitForServer();
  } catch (e) {
    console.error("Restart error:", e);
  } finally {
    btn.disabled = false;
    btn.textContent = "重启后端";
  }
});

// ============ Init ============
document.addEventListener("DOMContentLoaded", () => {
  waitForServer();
});
