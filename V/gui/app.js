// app.js — talks to window.pywebview.api. Falls back to a lightweight demo
// mode for the scan/results view if opened as a plain HTML file (no native
// backend); other native-only actions (channels, export) just report that
// they need the desktop app in that case.

const el = (id) => document.getElementById(id);
const hasNativeApi = () => typeof window.pywebview !== "undefined" && !!window.pywebview.api;

const state = {
  scanning: false,
  results: [],
  renderDirty: false,
};

// ==================== theme (dark / amoled / light, cycling) ====================
const THEME_ORDER = ["dark", "amoled", "light"];
const THEME_ICONS = {
  dark: `<svg viewBox="0 0 24 24" width="15" height="15"><path fill="currentColor" d="M20.742 13.045a8.088 8.088 0 0 1-2.077.273c-4.508 0-8.16-3.653-8.16-8.16 0-1.164.244-2.27.683-3.271A10.79 10.79 0 0 0 12.94 1C6.938 1 2.076 5.862 2.076 11.865c0 6.002 4.862 10.864 10.864 10.864 5.077 0 9.336-3.487 10.516-8.193a8.223 8.223 0 0 1-2.714-1.49z"/></svg>`,
  amoled: `<svg viewBox="0 0 24 24" width="15" height="15"><circle cx="12" cy="12" r="9" fill="currentColor"/></svg>`,
  light: `<svg viewBox="0 0 24 24" width="15" height="15"><path fill="currentColor" d="M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0-5a1 1 0 0 1 1 1v2a1 1 0 1 1-2 0V3a1 1 0 0 1 1-1zm0 18a1 1 0 0 1 1 1v2a1 1 0 1 1-2 0v-2a1 1 0 0 1 1-1zM4.22 4.22a1 1 0 0 1 1.42 0l1.42 1.42a1 1 0 1 1-1.42 1.42L4.22 5.64a1 1 0 0 1 0-1.42zm12.72 12.72a1 1 0 0 1 1.42 0l1.42 1.42a1 1 0 0 1-1.42 1.42l-1.42-1.42a1 1 0 0 1 0-1.42zM2 12a1 1 0 0 1 1-1h2a1 1 0 1 1 0 2H3a1 1 0 0 1-1-1zm18 0a1 1 0 0 1 1-1h2a1 1 0 1 1 0 2h-2a1 1 0 0 1-1-1zM4.22 19.78a1 1 0 0 1 0-1.42l1.42-1.42a1 1 0 1 1 1.42 1.42l-1.42 1.42a1 1 0 0 1-1.42 0zM16.94 6.34a1 1 0 0 1 0-1.42l1.42-1.42a1 1 0 1 1 1.42 1.42l-1.42 1.42a1 1 0 0 1-1.42 0z"/></svg>`,
};
function applyThemeIcon(theme) {
  el("btnAppearance").innerHTML = THEME_ICONS[theme] || THEME_ICONS.dark;
}
function initTheme() {
  const saved = THEME_ORDER.includes(localStorage.getItem("v2scan-theme"))
    ? localStorage.getItem("v2scan-theme")
    : "dark";
  document.documentElement.setAttribute("data-theme", saved);
  applyThemeIcon(saved);
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = THEME_ORDER[(THEME_ORDER.indexOf(cur) + 1) % THEME_ORDER.length];
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("v2scan-theme", next);
  applyThemeIcon(next);
}
initTheme();
el("btnAppearance").addEventListener("click", toggleTheme);

// ==================== window chrome (drag/resize via pywebview's own
// documented window.x/y/width/height + move()/resize() API) ====================
const MIN_WIN_W = 360;
const MIN_WIN_H = 240;

let latestDragTarget = null;
let dragInFlight = false;
function pumpDrag() {
  if (dragInFlight || !latestDragTarget) return;
  const { x, y } = latestDragTarget;
  latestDragTarget = null;
  dragInFlight = true;
  window.pywebview.api.move_window(x, y).finally(() => {
    dragInFlight = false;
    pumpDrag();
  });
}

let latestResizeTarget = null;
let resizeInFlight = false;
function pumpResize() {
  if (resizeInFlight || !latestResizeTarget) return;
  const { x, y, w, h } = latestResizeTarget;
  latestResizeTarget = null;
  resizeInFlight = true;
  window.pywebview.api.resize_and_move_window(x, y, w, h).finally(() => {
    resizeInFlight = false;
    pumpResize();
  });
}

function startWindowDrag(e) {
  if (!hasNativeApi()) return;
  e.preventDefault();
  window.pywebview.api.get_window_geometry().then((geom) => {
    const startMouseX = e.screenX, startMouseY = e.screenY;
    const startX = geom.x, startY = geom.y;
    const onMove = (ev) => {
      latestDragTarget = {
        x: startX + (ev.screenX - startMouseX),
        y: startY + (ev.screenY - startMouseY),
      };
      pumpDrag();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}

function startWindowResize(e, edge) {
  if (!hasNativeApi()) return;
  e.preventDefault();
  e.stopPropagation();
  window.pywebview.api.get_window_geometry().then((geom) => {
    const startMouseX = e.screenX, startMouseY = e.screenY;
    const startX = geom.x, startY = geom.y, startW = geom.width, startH = geom.height;
    const onMove = (ev) => {
      const dx = ev.screenX - startMouseX;
      const dy = ev.screenY - startMouseY;
      let x = startX, y = startY, w = startW, h = startH;
      if (edge.includes("right")) w = Math.max(MIN_WIN_W, startW + dx);
      if (edge.includes("left")) {
        w = Math.max(MIN_WIN_W, startW - dx);
        x = startX + (startW - w);
      }
      if (edge.includes("bottom")) h = Math.max(MIN_WIN_H, startH + dy);
      if (edge.includes("top")) {
        h = Math.max(MIN_WIN_H, startH - dy);
        y = startY + (startH - h);
      }
      latestResizeTarget = { x, y, w, h };
      pumpResize();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}

el("titlebar").addEventListener("mousedown", (e) => {
  if (e.target.closest(".wc-btn") || e.target.closest(".appearance-toggle")) return;
  startWindowDrag(e);
});
el("btnClose").addEventListener("click", () => hasNativeApi() && window.pywebview.api.close());
el("btnMin").addEventListener("click", () => hasNativeApi() && window.pywebview.api.minimize());
el("btnMax").addEventListener("click", () => hasNativeApi() && window.pywebview.api.toggle_maximize());

document.querySelectorAll(".resize-handle").forEach((handle) => {
  handle.addEventListener("mousedown", (e) => startWindowResize(e, handle.dataset.edge));
});

// ==================== source tabs (channel / subscription) ====================
el("sourceTabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".segment");
  if (!btn) return;
  document.querySelectorAll("#sourceTabs .segment").forEach((s) => s.classList.remove("active"));
  btn.classList.add("active");
  const isChannel = btn.dataset.source === "channel";
  el("channelSection").style.display = isChannel ? "" : "none";
  el("subscriptionSection").style.display = isChannel ? "none" : "";
});

// ==================== discovery mode tabs ====================
const discoveryNotes = {
  direct: "Scrapes t.me directly. Use this unless t.me itself is blocked for you.",
  proxy: "Routes the scraping requests through a Telegram SOCKS proxy link or a plain socks5://host:port.",
};
el("discoveryTabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".segment");
  if (!btn) return;
  document.querySelectorAll("#discoveryTabs .segment").forEach((s) => s.classList.remove("active"));
  btn.classList.add("active");
  const mode = btn.dataset.mode;
  el("discoveryProxyWrap").style.display = mode === "proxy" ? "" : "none";
  el("discoveryNote").textContent = discoveryNotes[mode] || "";
});
el("discoveryNote").textContent = discoveryNotes.direct;

// ==================== sidebar controls ====================
const limitSlider = el("limitSlider");
const limitValue = el("limitValue");
limitSlider.addEventListener("input", () => (limitValue.textContent = limitSlider.value));

const pingToggle = el("pingToggle");
const pingInputWrap = el("pingInputWrap");
pingToggle.addEventListener("change", () => {
  const on = pingToggle.checked;
  pingInputWrap.style.opacity = on ? "1" : "0.35";
  pingInputWrap.style.pointerEvents = on ? "auto" : "none";
});

// ==================== channel manager modal ====================
const channelModalOverlay = el("channelModalOverlay");

function openChannelModal() {
  channelModalOverlay.style.display = "flex";
  refreshChannelList();
}
function closeChannelModal() {
  channelModalOverlay.style.display = "none";
}
el("btnOpenChannels").addEventListener("click", openChannelModal);
el("btnCloseChannelModal").addEventListener("click", closeChannelModal);
channelModalOverlay.addEventListener("click", (e) => {
  if (e.target === channelModalOverlay) closeChannelModal();
});

async function refreshChannelList() {
  const listEl = el("channelList");
  if (!hasNativeApi()) {
    listEl.innerHTML = '<div class="channel-empty">Saved channels need the desktop app.</div>';
    return;
  }
  const res = await window.pywebview.api.list_channels();
  const channels = (res && res.channels) || [];
  if (channels.length === 0) {
    listEl.innerHTML = '<div class="channel-empty">No saved channels yet.</div>';
    return;
  }
  listEl.innerHTML = "";
  channels.forEach((ch) => {
    const row = document.createElement("div");
    row.className = "channel-row";
    row.innerHTML = `
      <div>
        <div class="channel-row-name">@${escapeHtml(ch.username)}</div>
        ${ch.label ? `<div class="channel-row-label">${escapeHtml(ch.label)}</div>` : ""}
      </div>
      <div class="channel-row-spacer"></div>
      <button class="btn-use" title="Use this channel">
        <svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M8 5v14l11-7z"/></svg>
      </button>
      <button class="btn-remove" title="Remove">
        <svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6zm2-8h2v6H8zm4 0h2v6h-2zM9 4h6l1 1h4v2H4V5h4z"/></svg>
      </button>
    `;
    row.querySelector(".btn-use").addEventListener("click", () => {
      el("channelInput").value = ch.username;
      closeChannelModal();
    });
    row.querySelector(".btn-remove").addEventListener("click", async () => {
      await window.pywebview.api.remove_channel(ch.username);
      refreshChannelList();
    });
    listEl.appendChild(row);
  });
}

el("btnAddChannel").addEventListener("click", async () => {
  const username = el("newChannelUsername").value.trim();
  const label = el("newChannelLabel").value.trim();
  if (!username || !hasNativeApi()) return;
  const res = await window.pywebview.api.add_channel(username, label);
  if (res && res.ok) {
    el("newChannelUsername").value = "";
    el("newChannelLabel").value = "";
    refreshChannelList();
  }
});

// ==================== scan lifecycle ====================
const scanBtn = el("scanBtn");
const scanBtnLabel = el("scanBtnLabel");
const statusText = el("statusText");
const progressFill = el("progressFill");
const resultsList = el("resultsList");
const rowElements = new Map();

function setStatus(text, cls) {
  statusText.textContent = text;
  statusText.className = "status-text" + (cls ? " " + cls : "");
}

function resetResults() {
  resultsList.innerHTML = "";
  rowElements.clear();
  state.results = [];
  el("statFound").textContent = "0";
  el("statAlive").textContent = "0";
  el("statTested").textContent = "0";
  progressFill.classList.remove("indeterminate");
  progressFill.style.width = "0%";
}

function currentSourceMode() {
  return document.querySelector("#sourceTabs .segment.active").dataset.source;
}
function currentDiscoveryMode() {
  return document.querySelector("#discoveryTabs .segment.active").dataset.mode;
}

function startScan() {
  if (state.scanning) {
    stopScan();
    return;
  }
  const source = currentSourceMode();
  const channel = el("channelInput").value.trim();
  const subscriptionUrl = el("subscriptionInput").value.trim();

  if (source === "channel" && !channel) {
    setStatus("Enter a channel username", "error");
    return;
  }
  if (source === "subscription" && !subscriptionUrl) {
    setStatus("Enter a subscription URL", "error");
    return;
  }

  resetResults();
  progressFill.classList.add("indeterminate");
  state.scanning = true;
  scanBtnLabel.textContent = "Stop Scan";
  scanBtn.classList.add("stopping");
  setStatus(source === "channel" ? "Scraping channel…" : "Fetching subscription…", "busy");

  const options = {
    source,
    channel,
    subscription_url: subscriptionUrl,
    proxies_only: el("proxiesOnlyToggle").checked,
    limit: parseInt(limitSlider.value, 10),
    min_ping_enabled: pingToggle.checked,
    min_ping_ms: parseInt(el("pingInput").value || "500", 10),
    test_ip: el("ipInput").value.trim(),
    discovery_mode: currentDiscoveryMode(),
    discovery_proxy_url: el("discoveryProxyInput").value.trim(),
  };

  if (hasNativeApi()) {
    window.pywebview.api.start_scan(options);
  } else {
    runDemoScan(options);
  }
}

function stopScan() {
  if (hasNativeApi()) window.pywebview.api.stop_scan();
  finishScan("Stopped");
}

function finishScan(label) {
  state.scanning = false;
  scanBtnLabel.textContent = "Start Scan";
  scanBtn.classList.remove("stopping");
  progressFill.classList.remove("indeterminate");
  progressFill.style.width = "100%";
  setStatus(label, label === "Stopped" ? "error" : "done");
}

scanBtn.addEventListener("click", startScan);
el("channelInput").addEventListener("keydown", (e) => { if (e.key === "Enter") startScan(); });
el("subscriptionInput").addEventListener("keydown", (e) => { if (e.key === "Enter") startScan(); });

// ==================== results rendering (sorted by ping, incremental) ====================
function sortKey(r) {
  if (!r.alive || r.ping_ms == null) return [1, 0];
  return [0, r.ping_ms];
}

function scheduleRender() {
  state.renderDirty = true;
}

function renderLoop() {
  if (state.renderDirty) {
    state.renderDirty = false;
    doRender();
  }
  requestAnimationFrame(renderLoop);
}
requestAnimationFrame(renderLoop);

function doRender() {
  const found = state.results.length;
  const alive = state.results.filter((r) => r.alive).length;
  el("statFound").textContent = found;
  el("statAlive").textContent = alive;
  el("statTested").textContent = found;

  const sorted = [...state.results].sort((a, b) => {
    const [ga, pa] = sortKey(a);
    const [gb, pb] = sortKey(b);
    return ga !== gb ? ga - gb : pa - pb;
  });

  if (sorted.length === 0) {
    rowElements.clear();
    resultsList.innerHTML = `
      <div class="empty-state" id="emptyState">
        <svg viewBox="0 0 24 24" width="44" height="44"><path fill="currentColor" opacity="0.35" d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm1 15h-2v-2h2zm0-4h-2V7h2z"/></svg>
        <p>Enter a channel and start a scan</p>
      </div>`;
    return;
  }

  const stillEmpty = resultsList.querySelector(".empty-state");
  if (stillEmpty) resultsList.innerHTML = "";

  const seenRaws = new Set();
  let prevEl = null;
  sorted.forEach((cfg) => {
    seenRaws.add(cfg.raw);
    let rowEl = rowElements.get(cfg.raw);
    if (!rowEl) {
      rowEl = document.createElement("div");
      rowElements.set(cfg.raw, rowEl);
    }
    applyRowContent(rowEl, cfg);
    const desiredNext = prevEl ? prevEl.nextSibling : resultsList.firstChild;
    if (desiredNext !== rowEl) {
      resultsList.insertBefore(rowEl, desiredNext);
    }
    prevEl = rowEl;
  });

  for (const raw of [...rowElements.keys()]) {
    if (!seenRaws.has(raw)) rowElements.delete(raw);
  }
}

function protoClass(p) { return "badge-" + p.toLowerCase(); }

function pingClass(alive, ms) {
  if (!alive) return "ping-dead";
  if (ms <= 150) return "ping-fast";
  if (ms <= 400) return "ping-mid";
  return "ping-slow";
}

function applyRowContent(row, cfg) {
  row.className = "row" + (cfg.alive ? "" : " row-dead");

  const pClass = pingClass(cfg.alive, cfg.ping_ms);
  const pingLabel = cfg.alive ? `${cfg.ping_ms} ms` : "unreachable";

  row.innerHTML = `
    <span class="flag-cell">${cfg.flag || "🌐"}</span>
    <span class="badge ${protoClass(cfg.protocol)}">${cfg.protocol}</span>
    <span class="cell-host">${escapeHtml(cfg.host)}:${cfg.port}</span>
    <span class="cell-remark">${escapeHtml(cfg.remark || "—")}</span>
    <span class="ping-badge ${pClass}"><span class="ping-dot"></span>${pingLabel}</span>
    <button class="copy-btn" title="Copy link">
      <svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11z"/></svg>
    </button>
  `;

  row.querySelector(".copy-btn").addEventListener("click", (e) => {
    const btn = e.currentTarget;
    navigator.clipboard?.writeText(cfg.raw).catch(() => {});
    btn.classList.add("copied");
    setTimeout(() => btn.classList.remove("copied"), 900);
  });
}

// ==================== export ====================
el("btnExport").addEventListener("click", async () => {
  if (!hasNativeApi()) {
    setStatus("Export needs the desktop app", "error");
    return;
  }
  const res = await window.pywebview.api.export_valid();
  if (res && res.ok) {
    setStatus(`Exported ${res.count} configs`, "done");
  } else if (res && res.error !== "cancelled") {
    setStatus(res.error || "Export failed", "error");
  }
});

// ==================== native -> JS event bridge ====================
window.__onNative = function (event, payload) {
  switch (event) {
    case "scan_started":
      setStatus(`Scanning ${payload.channel}…`, "busy");
      break;
    case "scrape_progress":
      setStatus(`Found ${payload.found} items (page ${payload.pages})…`, "busy");
      break;
    case "scrape_done":
      progressFill.classList.remove("indeterminate");
      setStatus(`Testing ${payload.count} items…`, "busy");
      break;
    case "config_result":
      state.results.push(payload);
      scheduleRender();
      break;
    case "scan_finished":
      finishScan(`Done — ${payload.alive}/${payload.tested} reachable`);
      break;
    case "scan_stopped":
      finishScan("Stopped");
      break;
    case "scan_error":
      finishScan("Error");
      setStatus(payload.message, "error");
      break;
  }
};

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

// ==================== browser-preview demo mode (no python backend) ====================
function runDemoScan(options) {
  const protocols = ["vless", "vmess", "trojan", "ss", "socks5"];
  const flags = ["🇩🇪", "🇳🇱", "🇺🇸", "🇸🇬", "🇮🇷", "🌐"];
  const total = Math.min(options.limit, 40);
  progressFill.classList.remove("indeterminate");
  setStatus(`Testing ${total} items… (preview mode)`, "busy");

  let i = 0;
  const timer = setInterval(() => {
    if (i >= total || !state.scanning) {
      clearInterval(timer);
      if (state.scanning) {
        const alive = state.results.filter((r) => r.alive).length;
        finishScan(`Done — ${alive}/${state.results.length} reachable`);
      }
      return;
    }
    const alive = Math.random() > 0.35;
    state.results.push({
      protocol: protocols[Math.floor(Math.random() * protocols.length)],
      flag: flags[Math.floor(Math.random() * flags.length)],
      host: `${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}`,
      port: [443, 8443, 2083, 8880][Math.floor(Math.random() * 4)],
      remark: ["Germany", "Netherlands", "US Node", "Singapore", ""][Math.floor(Math.random() * 5)],
      raw: "vless://demo" + i,
      alive,
      ping_ms: alive ? Math.floor(Math.random() * 500) + 30 : null,
    });
    scheduleRender();
    i += 1;
  }, 90);
}
