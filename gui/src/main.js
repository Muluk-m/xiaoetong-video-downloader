// ============ API 配置 ============
const API_BASE = "http://127.0.0.1:19528";

// ============ 状态 ============
let currentTaskId = null;
let pollTimer = null;
let videos = [];

// ============ 工具函数 ============
async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function showMessage(el, text, type = "info") {
  el.textContent = text;
  el.className = `message show ${type}`;
  setTimeout(() => el.classList.remove("show"), 5000);
}

// ============ 标签页切换 ============
$$(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach(t => t.classList.remove("active"));
    $$(".tab-content").forEach(c => c.classList.remove("active"));
    tab.classList.add("active");
    $(`#tab-${tab.dataset.tab}`).classList.add("active");
  });
});

// ============ 后端健康检查 ============
async function checkServer() {
  const badge = $("#server-status");
  try {
    await api("/api/config");
    badge.textContent = "已连接";
    badge.className = "status-badge status-ok";
    return true;
  } catch {
    badge.textContent = "未连接";
    badge.className = "status-badge status-error";
    return false;
  }
}

async function waitForServer() {
  const badge = $("#server-status");
  badge.textContent = "连接中...";
  badge.className = "status-badge status-connecting";

  for (let i = 0; i < 30; i++) {
    if (await checkServer()) {
      loadConfig();
      return;
    }
    await new Promise(r => setTimeout(r, 1000));
  }
  badge.textContent = "连接失败";
  badge.className = "status-badge status-error";
}

// ============ 配置页 ============
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
    }
  } catch (e) {
    console.error("加载配置失败:", e);
  }
}

$("#btn-auto-cookie").addEventListener("click", async () => {
  const btn = $("#btn-auto-cookie");
  const hint = $("#cookie-hint");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>读取中...';
  hint.textContent = "";

  try {
    const data = await api("/api/cookies");
    if (data.success) {
      $("#input-cookie").value = data.cookie;
      hint.textContent = data.message;
      hint.style.color = "var(--success)";
    } else {
      hint.textContent = data.message;
      hint.style.color = "var(--danger)";
    }
  } catch (e) {
    hint.textContent = "读取失败: " + e.message;
    hint.style.color = "var(--danger)";
  } finally {
    btn.disabled = false;
    btn.textContent = "自动获取";
  }
});

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

    if (!config.cookie || !config.app_id || !config.product_id) {
      showMessage(msg, "请填写 Cookie、App ID 和 Product ID", "error");
      return;
    }

    const data = await api("/api/config", {
      method: "POST",
      body: JSON.stringify(config),
    });

    showMessage(msg, data.success ? "配置已保存" : "保存失败", data.success ? "success" : "error");
  } catch (e) {
    showMessage(msg, "保存失败: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
});

$("#btn-check-env").addEventListener("click", async () => {
  const btn = $("#btn-check-env");
  const msg = $("#config-message");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>检查中...';

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

// ============ 视频列表页 ============
$("#btn-refresh-videos").addEventListener("click", async () => {
  const btn = $("#btn-refresh-videos");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>加载中...';

  try {
    const data = await api("/api/videos");
    if (data.success) {
      videos = data.videos;
      renderVideoList(videos);
      $("#video-count").textContent = `共 ${videos.length} 个视频`;
    } else {
      $("#video-list").innerHTML = `<div class="empty-state">${data.message || "获取失败"}</div>`;
    }
  } catch (e) {
    $("#video-list").innerHTML = `<div class="empty-state">获取失败: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "刷新列表";
  }
});

function renderVideoList(videos) {
  const container = $("#video-list");
  if (!videos.length) {
    container.innerHTML = '<div class="empty-state">没有找到视频</div>';
    return;
  }

  container.innerHTML = videos.map((v, i) => {
    const title = v.resource_title || "未知标题";
    const id = v.resource_id || "";
    const date = v.start_at || "";
    const progress = v.learn_progress || 0;

    return `
      <div class="video-item" data-id="${id}">
        <input type="checkbox" class="video-checkbox" value="${id}" />
        <span class="video-index">${i + 1}</span>
        <div class="video-info">
          <div class="video-title" title="${title}">${title}</div>
          <div class="video-meta">
            <span>ID: ${id}</span>
            <span>${date}</span>
          </div>
        </div>
        <div class="video-progress">
          <span style="font-size:12px;color:var(--text-secondary)">${progress}%</span>
          <div class="progress-mini">
            <div class="progress-mini-fill" style="width:${progress}%"></div>
          </div>
        </div>
      </div>
    `;
  }).join("");

  // 点击行也能切换 checkbox
  container.querySelectorAll(".video-item").forEach(item => {
    item.addEventListener("click", (e) => {
      if (e.target.type === "checkbox") return;
      const cb = item.querySelector(".video-checkbox");
      cb.checked = !cb.checked;
    });
  });
}

$("#btn-select-all").addEventListener("click", () => {
  $$(".video-checkbox").forEach(cb => cb.checked = true);
});

$("#btn-deselect-all").addEventListener("click", () => {
  $$(".video-checkbox").forEach(cb => cb.checked = false);
});

$("#btn-download-selected").addEventListener("click", async () => {
  const selected = Array.from($$(".video-checkbox:checked")).map(cb => cb.value);
  if (!selected.length) {
    alert("请先选择要下载的视频");
    return;
  }
  await startDownload(selected);
});

// ============ 下载任务页 ============
async function startDownload(resourceIds = []) {
  // 切换到下载页
  $$(".tab").forEach(t => t.classList.remove("active"));
  $$(".tab-content").forEach(c => c.classList.remove("active"));
  $$(".tab")[2].classList.add("active");
  $("#tab-download").classList.add("active");

  // 重置UI
  $("#download-log").innerHTML = "";
  $("#download-results").style.display = "none";
  $("#download-progress-bar").style.display = "block";
  $("#segment-progress-bar").style.display = "block";
  $("#segment-pct").style.display = "block";
  $("#btn-cancel-download").style.display = "inline-block";
  $("#dl-status").textContent = "启动中...";
  $("#dl-progress").textContent = "-";
  $("#dl-current").textContent = "-";
  $("#dl-segments").textContent = "-";
  $("#dl-bar").style.width = "0%";
  $("#seg-bar").style.width = "0%";
  $("#segment-pct").textContent = "";

  try {
    const data = await api("/api/download", {
      method: "POST",
      body: JSON.stringify({
        resource_ids: resourceIds,
        nocache: false,
        auto_transcode: true,
      }),
    });

    if (data.success) {
      currentTaskId = data.task_id;
      startPolling(currentTaskId);
    } else {
      $("#dl-status").textContent = "启动失败";
      appendLog("error", data.message || "启动下载失败");
    }
  } catch (e) {
    $("#dl-status").textContent = "错误";
    appendLog("error", "启动下载失败: " + e.message);
  }
}

function startPolling(taskId) {
  if (pollTimer) clearInterval(pollTimer);

  let lastLogLen = 0;

  pollTimer = setInterval(async () => {
    try {
      const task = await api(`/api/download/status/${taskId}`);

      // 更新状态
      const statusMap = {
        running: "下载中",
        completed: "已完成",
        failed: "失败",
        cancelled: "已取消",
      };
      $("#dl-status").textContent = statusMap[task.status] || task.status;

      // 更新视频级进度
      if (task.total > 0) {
        $("#dl-progress").textContent = `${task.current} / ${task.total} 个视频`;
        const pct = Math.round((task.current / task.total) * 100);
        $("#dl-bar").style.width = `${pct}%`;
      }

      // 更新当前标题
      if (task.current_title) {
        $("#dl-current").textContent = task.current_title;
      }

      // 更新分片级进度
      if (task.segments_total > 0) {
        const segDl = task.segments_downloaded;
        const segTotal = task.segments_total;
        const segPct = Math.round((segDl / segTotal) * 100);
        $("#dl-segments").textContent = `${segDl} / ${segTotal}`;
        $("#seg-bar").style.width = `${segPct}%`;
        $("#segment-pct").textContent = `分片: ${segPct}% (${segDl}/${segTotal})`;
      } else {
        $("#dl-segments").textContent = "等待中...";
        $("#seg-bar").style.width = "0%";
      }

      // 追加新日志
      if (task.progress && task.progress.length > lastLogLen) {
        const newLogs = task.progress.slice(lastLogLen);
        newLogs.forEach(log => appendLog(log.type, log.message));
        lastLogLen = task.progress.length;
      }

      // 任务结束
      if (["completed", "failed", "cancelled"].includes(task.status)) {
        clearInterval(pollTimer);
        pollTimer = null;
        currentTaskId = null;
        $("#btn-cancel-download").style.display = "none";
        $("#segment-progress-bar").style.display = "none";
        $("#segment-pct").style.display = "none";

        if (task.status === "completed") {
          $("#dl-bar").style.width = "100%";
          $("#dl-segments").textContent = "完成";
        }

        // 显示结果
        showResults(task.results);
      }
    } catch (e) {
      console.error("轮询失败:", e);
    }
  }, 800);
}

function appendLog(type, message) {
  const log = $("#download-log");
  if (log.querySelector(".empty-state")) {
    log.innerHTML = "";
  }
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

  if (results.success && results.success.length) {
    html += results.success.map(r =>
      `<div class="result-item result-success">
        <span class="result-icon">OK</span>
        <span>${r.title}</span>
      </div>`
    ).join("");
  }

  if (results.failed && results.failed.length) {
    html += results.failed.map(r =>
      `<div class="result-item result-failed">
        <span class="result-icon">X</span>
        <span>${r.title} - ${r.message}</span>
      </div>`
    ).join("");
  }

  content.innerHTML = html || '<div class="empty-state">无结果</div>';
}

$("#btn-cancel-download").addEventListener("click", async () => {
  if (!currentTaskId) return;
  try {
    await api(`/api/download/cancel/${currentTaskId}`, { method: "POST" });
    appendLog("info", "正在取消下载...");
  } catch (e) {
    appendLog("error", "取消失败: " + e.message);
  }
});

// ============ 初始化 ============
document.addEventListener("DOMContentLoaded", () => {
  waitForServer();
});
