// ============ API ============
const API_BASE = "http://127.0.0.1:19528";

// ============ State ============
let currentTaskId = null;
let pollTimer = null;
let videos = [];
let selectedCount = 0;

// ============ Helpers ============
async function api(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
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

// ============ Navigation ============
$$(".rail-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    $$(".rail-btn").forEach(b => b.classList.remove("active"));
    $$(".panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
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
  } catch {
    dot.className = "conn-dot conn-error";
    dot.title = "未连接";
    return false;
  }
}

async function waitForServer() {
  for (let i = 0; i < 30; i++) {
    if (await checkServer()) { loadConfig(); return; }
    await new Promise(r => setTimeout(r, 1000));
  }
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

      // Show parsed info if we have saved values
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
  } catch {}
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
    } else {
      hint.textContent = "未找到登录信息，请先用 Chrome 打开小鹅通并登录";
      hint.style.color = "var(--red)";
    }
  } catch (e) {
    hint.textContent = "读取失败: " + e.message;
    hint.style.color = "var(--red)";
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
    } else {
      hint.textContent = data.message || "无法识别链接，请确认是小鹅通课程页面的链接";
      hint.style.color = "var(--red)";
    }
  } catch (e) {
    hint.textContent = "解析失败: " + e.message;
    hint.style.color = "var(--red)";
  }
}

// ============ Save Config ============
$("#btn-save-config").addEventListener("click", async () => {
  const btn = $("#btn-save-config");
  const msg = $("#config-message");
  btn.disabled = true;

  try {
    const config = {
      cookie: $("#input-cookie").value.trim(),
      app_id: $("#input-app-id").value.trim(),
      product_id: $("#input-product-id").value.trim(),
      download_dir: $("#input-download-dir").value.trim() || "download",
      max_workers: parseInt($("#input-max-workers").value) || 5,
    };

    if (!config.cookie) {
      showMessage(msg, "请先完成第一步：同步登录状态", "error");
      return;
    }
    if (!config.app_id || !config.product_id) {
      showMessage(msg, "请先完成第二步：填写课程链接", "error");
      return;
    }

    const data = await api("/api/config", { method: "POST", body: JSON.stringify(config) });
    showMessage(msg, data.success ? "设置已保存，可以去「课程」页面加载视频了" : "保存失败", data.success ? "success" : "error");
  } catch (e) {
    showMessage(msg, "保存失败: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
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
    showMessage(msg, "检查失败: " + e.message, "error");
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
    $("#video-list").innerHTML = `<div class="empty"><p>获取失败: ${e.message}</p></div>`;
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
    const progress = v.learn_progress || 0;
    return `
      <div class="video-item" data-id="${id}">
        <input type="checkbox" class="video-checkbox" value="${id}" />
        <span class="vi-index">${i + 1}</span>
        <div class="vi-info">
          <div class="vi-title" title="${title}">${title}</div>
          <div class="vi-meta">${date}</div>
        </div>
        <div class="vi-progress" title="学习进度">
          已学 ${progress}%
          <div class="vi-bar"><div class="vi-bar-fill" style="width:${progress}%"></div></div>
        </div>
      </div>`;
  }).join("");

  container.querySelectorAll(".video-item").forEach(item => {
    item.addEventListener("click", (e) => {
      if (e.target.type === "checkbox") { updateSelectedCount(); return; }
      const cb = item.querySelector(".video-checkbox");
      cb.checked = !cb.checked;
      updateSelectedCount();
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
    appendLog("error", "启动下载失败: " + e.message);
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
    appendLog("error", "取消失败: " + e.message);
  }
});

// ============ Init ============
document.addEventListener("DOMContentLoaded", () => {
  waitForServer();
});
