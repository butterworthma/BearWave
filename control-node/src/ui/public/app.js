const socket = io();

const nodeGrid = document.getElementById("nodeGrid");
const modePill = document.getElementById("modePill");
const alarmBanner = document.getElementById("alarmBanner");
const alarmText = document.getElementById("alarmText");
const silenceBtn = document.getElementById("silenceBtn");
const utcClock = document.getElementById("utcClock");
const nodeCount = document.getElementById("nodeCount");
const alarmCount = document.getElementById("alarmCount");
const missingCount = document.getElementById("missingCount");
const healthyCount = document.getElementById("healthyCount");
const systemStatus = document.getElementById("systemStatus");
const uptimeValue = document.getElementById("uptimeValue");
const cpuValue = document.getElementById("cpuValue");
const tempValue = document.getElementById("tempValue");
const storageValue = document.getElementById("storageValue");
const imageDialog = document.getElementById("imageDialog");
const imageDialogImg = document.getElementById("imageDialogImg");
const imageDialogCaption = document.getElementById("imageDialogCaption");
const closeImageBtn = document.getElementById("closeImageBtn");
const navButtons = document.querySelectorAll(".bottom-nav button[data-view]");
const menuButton = document.getElementById("menuButton");
const windowMenu = document.getElementById("windowMenu");
const timeSyncBtn = document.getElementById("timeSyncBtn");

/*
 * The dashboard is deliberately a small browser application with no build
 * step. That makes it easy to modify directly on a Raspberry Pi during field
 * testing. All live state is kept in these arrays and refreshed by REST calls
 * at startup plus Socket.IO updates while the app is open.
 */
let config = null;
let nodes = [];
let images = [];
let historyEvents = [];
let logLines = [];
let activeView = "dashboard";
let audioContext = null;
let alarmMuted = false;
const startedAt = Date.now();

init();

async function init() {
  startClock();

  try {
    /*
     * Load the initial snapshot before subscribing to live updates. This gives
     * the kiosk a complete screen immediately after Chromium opens, even if no
     * fresh RF traffic arrives for several minutes.
     */
    const [configRes, nodesRes, healthRes, imagesRes, historyRes] = await Promise.all([
      fetch("/api/config"),
      fetch("/api/nodes"),
      fetch("/api/health"),
      fetch("/api/images"),
      fetch("/api/history")
    ]);

    config = await configRes.json();
    nodes = await nodesRes.json();
    const health = await healthRes.json();
    images = await imagesRes.json();
    historyEvents = await historyRes.json();

    modePill.textContent = health.simulate ? "Simulator" : "Live JS8Call";
    render();
  } catch (err) {
    console.error("Dashboard startup failed:", err);
    modePill.textContent = "Offline";
    systemStatus.textContent = "CHECK";
    systemStatus.className = "bad";
  }

  socket.on("nodes_snapshot", (snapshot) => {
    /*
     * The server emits periodic full snapshots so the UI recovers from any
     * missed per-node events without requiring a browser refresh.
     */
    nodes = snapshot;
    render();
  });

  socket.on("node_update", (updatedNode) => {
    const idx = nodes.findIndex((n) => n.nodeId === updatedNode.nodeId);
    if (idx >= 0) {
      nodes[idx] = updatedNode;
    } else {
      nodes.push(updatedNode);
    }
    render();
  });

  socket.on("alarm", (alarm) => {
    alarmBanner.classList.remove("hidden");
    alarmText.textContent = `Node ${alarm.nodeId} reported ${alarm.messageType}`;
    addHistoryEvent({
      ts: new Date().toISOString(),
      event: "alarm",
      node: alarm.nodeId,
      text: `Node ${alarm.nodeId} reported ${alarm.messageType}`
    });
    if (!alarmMuted && config?.alerts?.soundEnabled) {
      playAlarmTone();
    }
  });

  socket.on("event", (evt) => {
    addHistoryEvent({
      ts: evt.ts || new Date().toISOString(),
      event: "event",
      text: evt.text || JSON.stringify(evt)
    });
  });

  socket.on("sstv_image", (image) => {
    /*
     * A decoded SSTV image may arrive before the server has linked it to a
     * specific node. Store it locally and run the same conservative fallback
     * matching used during initial page load.
     */
    upsertImage(image);
    addHistoryEvent({
      ts: image.receivedAtIso || new Date().toISOString(),
      event: "sstv_image",
      text: `SSTV image received: ${image.filename}`,
      image
    });
    attachImageFallback();
    render();
  });

  bindNavigation();
  setInterval(renderFooter, 30000);
}

function startClock() {
  const tick = () => {
    const now = new Date();
    utcClock.textContent = now.toISOString().replace("T", " ").slice(0, 19);
  };
  tick();
  setInterval(tick, 1000);
}

function render() {
  attachImageFallback();
  renderSummary();
  renderActiveView();
  renderFooter();
}

function renderSummary() {
  const alarms = nodes.filter((node) => node.alarmActive).length;
  const missing = nodes.filter((node) => node.health === "yellow" || node.health === "red").length;
  const healthy = nodes.filter((node) => node.health === "green" && !node.alarmActive).length;

  nodeCount.textContent = nodes.length;
  alarmCount.textContent = alarms;
  missingCount.textContent = missing;
  healthyCount.textContent = healthy;

  document.body.classList.toggle("has-alarm", alarms > 0);
  if (alarms === 0) {
    alarmBanner.classList.add("hidden");
  }
}

function renderActiveView() {
  /*
   * The bottom navigation is view switching inside one page. The Pi display
   * stays in kiosk mode; no browser navigation or page reload is required.
   */
  if (activeView === "nodes") return renderNodeList();
  if (activeView === "alerts") return renderAlerts();
  if (activeView === "history") return renderHistory();
  if (activeView === "map") return renderMapPlaceholder();
  if (activeView === "logs") return renderLogs();
  return renderDashboard();
}

function renderDashboard() {
  if (!nodes.length) {
    nodeGrid.innerHTML = `
      <article class="node-card empty-card">
        <div class="node-main">
          <div class="state-symbol red">?</div>
          <div>
            <h2>No Nodes Heard</h2>
            <p>Waiting for the first JS8Call message.</p>
          </div>
        </div>
      </article>
    `;
    return;
  }

  nodeGrid.innerHTML = nodes
    .slice()
    .sort(sortNodes)
    .map(renderNodeCard)
    .join("");

  bindImageThumbs();
  bindCardButtons();
}

function renderNodeList() {
  nodeGrid.innerHTML = `
    <section class="view-panel wide-view">
      <div class="view-heading">
        <h2>Reporting Nodes</h2>
        <span>${nodes.length} known</span>
      </div>
      ${nodes.length ? `
        <div class="data-table">
          <div class="data-row table-head">
            <span>Node</span><span>State</span><span>Last Heartbeat</span><span>Battery</span><span>SSTV</span>
          </div>
          ${nodes.slice().sort(sortNodes).map((node) => {
            const state = getNodeState(node);
            const battery = getBattery(node);
            return `
              <div class="data-row">
                <strong>${escapeHtml(node.nodeId)}</strong>
                <span class="state-text ${state.key}">${escapeHtml(state.label)}</span>
                <span>${escapeHtml(node.lastHeard ? `${formatUtcTime(node.lastHeard)} (${formatDuration(node.ageMs || 0)} ago)` : "No heartbeat")}</span>
                <span>${escapeHtml(battery.percent)}</span>
                <span>${escapeHtml(formatImageStatus(node))}</span>
              </div>
            `;
          }).join("")}
        </div>
      ` : renderEmptyView("No nodes reporting", "Waiting for the first decoded BearWave message.")}
    </section>
  `;
}

function renderAlerts() {
  const alerts = nodes.filter((node) => node.alarmActive || node.lowBattery || node.faultActive);

  nodeGrid.innerHTML = `
    <section class="view-panel wide-view">
      <div class="view-heading">
        <h2>Current Alerts</h2>
        <span>${alerts.length} active</span>
      </div>
      ${alerts.length ? alerts.map((node) => {
        const state = getNodeState(node);
        return `
          <article class="alert-item ${state.key}">
            <div>
              <strong>${escapeHtml(node.nodeId)}</strong>
              <span>${escapeHtml(state.label)}</span>
            </div>
            <div>
              <span>${escapeHtml(node.lastType || "Alert")}</span>
              <em>${escapeHtml(node.lastHeard ? `${formatUtcTime(node.lastHeard)} (${formatDuration(node.ageMs || 0)} ago)` : "No heartbeat")}</em>
            </div>
            <div class="node-actions">
              <button data-action="ack" data-node="${escapeAttr(node.nodeId)}" type="button">Ack</button>
              <button data-action="clear" data-node="${escapeAttr(node.nodeId)}" type="button">Clear</button>
            </div>
          </article>
        `;
      }).join("") : renderEmptyView("No current alerts", "All known nodes are clear.")}
    </section>
  `;
  bindCardButtons();
}

function renderHistory() {
  nodeGrid.innerHTML = `
    <section class="view-panel wide-view">
      <div class="view-heading">
        <h2>History</h2>
        <span>${historyEvents.length} recent events</span>
      </div>
      <div class="event-list">
        ${historyEvents.length ? historyEvents.slice(0, 80).map(renderHistoryItem).join("") : renderEmptyView("No history yet", "Events will appear here as messages, ACKs, and images arrive.")}
      </div>
    </section>
  `;
}

function renderMapPlaceholder() {
  nodeGrid.innerHTML = `
    <section class="view-panel wide-view map-placeholder">
      <div class="view-heading">
        <h2>Map</h2>
        <span>Planned</span>
      </div>
      ${renderEmptyView("Map view reserved", "Node mapping can be added once the field locations are final.")}
    </section>
  `;
}

async function renderLogs() {
  nodeGrid.innerHTML = `
    <section class="view-panel wide-view">
      <div class="view-heading">
        <h2>Control Node Log</h2>
        <span>Loading...</span>
      </div>
      <pre class="log-view">Loading control-node log...</pre>
    </section>
  `;

  await refreshLogs();
  /*
   * Logs are fetched on demand when the tab is opened. This avoids repeatedly
   * moving large text around while the dashboard tab is showing node status.
   */
  nodeGrid.innerHTML = `
    <section class="view-panel wide-view">
      <div class="view-heading">
        <h2>Control Node Log</h2>
        <span>${logLines.length} lines</span>
      </div>
      <pre class="log-view">${escapeHtml(logLines.join("\n") || "No log lines available.")}</pre>
    </section>
  `;
}

function renderHistoryItem(evt) {
  return `
    <div class="event-row">
      <time>${escapeHtml(formatUtcTime(evt.ts || evt.eventUtc))}</time>
      <strong>${escapeHtml(formatEventName(evt.event))}</strong>
      <span>${escapeHtml(formatEventText(evt))}</span>
    </div>
  `;
}

function renderEmptyView(title, body) {
  return `
    <div class="empty-view">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(body)}</span>
    </div>
  `;
}

function bindNavigation() {
  navButtons.forEach((button) => {
    button.onclick = async () => {
      activeView = button.dataset.view || "dashboard";
      navButtons.forEach((btn) => btn.classList.toggle("active", btn === button));
      await renderActiveView();
    };
  });
}

async function refreshLogs() {
  try {
    const res = await fetch("/api/logs?lines=160");
    if (!res.ok) throw new Error(`log request failed: ${res.status}`);
    const data = await res.json();
    logLines = data.lines || [];
  } catch (err) {
    console.error("Log refresh failed:", err);
    logLines = ["Unable to read control-node log."];
  }
}

function addHistoryEvent(evt) {
  historyEvents.unshift(evt);
  historyEvents = historyEvents.slice(0, 160);
  if (activeView === "history") {
    renderHistory();
  }
}

function formatEventName(name) {
  if (!name) return "event";
  return String(name).replaceAll("_", " ");
}

function formatEventText(evt) {
  if (evt.text) return evt.text;
  if (evt.node && evt.event) return `${evt.event} ${evt.node}`;
  if (evt.raw) {
    try {
      const raw = JSON.parse(evt.raw);
      return `${raw.type || "JS8"} ${raw.value || ""}`.trim();
    } catch (_err) {
      return evt.raw;
    }
  }
  if (evt.image?.filename) return evt.image.filename;
  return JSON.stringify(evt);
}

function renderNodeCard(node, index) {
  const state = getNodeState(node);
  const image = getNodeImage(node);
  const trapLabel = `Trap ${index + 1} / Node ${node.nodeId}`;
  const lastHeard = node.lastHeard ? formatUtcTime(node.lastHeard) : "--:--:-- UTC";
  const age = node.lastHeard ? `${formatDuration(node.ageMs || 0)} ago` : "No heartbeat";
  const battery = getBattery(node);
  const signal = getSignal(node);
  const location = getLocation(node);

  return `
    <article class="node-card ${state.key}">
      <div class="node-main">
        <div class="state-symbol ${state.key}">${state.symbol}</div>
        <div class="node-heading">
          <h2>${escapeHtml(trapLabel)}</h2>
          <strong>${state.label}</strong>
          <span>${escapeHtml(state.detail)}</span>
        </div>
        <div class="signal-bars ${state.key}" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
      </div>

      <div class="node-details">
        ${detailRow("heart", "Last Heartbeat", lastHeard, age, state.key)}
        ${detailRow("battery", "Battery", battery.percent, battery.bars, state.key)}
        ${detailRow("signal", "Signal / SNR", signal, "", state.key)}
        ${detailRow("pin", "Location", location.primary, location.secondary, state.key)}
        ${detailRow("radio", node.alarmActive ? "Trap Status" : "Radio Link", node.alarmActive ? "TRIGGERED" : "Connected", image ? "Image received" : formatImageStatus(node), state.key)}
      </div>

      <div class="image-row ${image ? "" : "empty"}">
        ${renderImageThumb(node, image)}
        <div class="node-actions">
          <button data-action="ack" data-node="${escapeAttr(node.nodeId)}" type="button">Ack</button>
          <button data-action="clear" data-node="${escapeAttr(node.nodeId)}" type="button">Clear</button>
        </div>
      </div>
    </article>
  `;
}

function detailRow(icon, label, value, subValue, state) {
  return `
    <div class="detail-row">
      <span class="row-icon ${icon} ${state}"></span>
      <span class="row-label">${escapeHtml(label)}</span>
      <span class="row-value">
        <strong>${escapeHtml(value || "-")}</strong>
        ${subValue ? `<em>${escapeHtml(subValue)}</em>` : ""}
      </span>
    </div>
  `;
}

function renderImageThumb(node, image) {
  /*
   * The thumbnail is a real button rather than a bare image so it remains easy
   * to use on the 7 inch touch screen and opens the full-size received image.
   */
  if (!image?.url) {
    return `
      <div class="sstv-placeholder">
        <strong>SSTV</strong>
        <span>${escapeHtml(formatImageStatus(node))}</span>
      </div>
    `;
  }

  const caption = `${node.nodeId} ${formatUtcTime(image.receivedAt || image.receivedAtIso)}`;
  return `
    <button class="sstv-thumb" type="button" data-image-url="${escapeAttr(image.url)}" data-image-caption="${escapeAttr(caption)}">
      <img src="${escapeAttr(image.url)}" alt="SSTV image for ${escapeAttr(node.nodeId)}">
      <span>
        <strong>SSTV Image</strong>
        <em>${escapeHtml(formatUtcTime(image.receivedAt || image.receivedAtIso))}</em>
      </span>
    </button>
  `;
}

function getNodeImage(node) {
  if (node.latestImage?.url) {
    return node.latestImage;
  }

  /*
   * Preferred association is server-side and stored as node.latestImage. The
   * fallback below is only for older images or manual test files: match node ID
   * in the filename, or attach the newest image when there is only one node.
   */
  return images.find((image) =>
    image.filename.toUpperCase().includes(node.nodeId.toUpperCase())
  ) || (nodes.length === 1 ? images[0] : null);
}

function bindImageThumbs() {
  document.querySelectorAll(".sstv-thumb").forEach((thumb) => {
    thumb.onclick = () => {
      imageDialogImg.src = thumb.dataset.imageUrl;
      imageDialogCaption.textContent = thumb.dataset.imageCaption || "SSTV image";
      imageDialog.showModal();
    };
  });
}

function bindCardButtons() {
  document.querySelectorAll("button[data-action='ack']").forEach((btn) => {
    btn.onclick = async () => {
      const res = await fetch(`/api/nodes/${encodeURIComponent(btn.dataset.node)}/ack-alarm`, { method: "POST" });
      if (!res.ok) return;
      const updatedNode = await res.json();
      const idx = nodes.findIndex((node) => node.nodeId === updatedNode.nodeId);
      if (idx >= 0) {
        nodes[idx] = updatedNode;
        addHistoryEvent({
          ts: new Date().toISOString(),
          event: "operator_ack",
          node: updatedNode.nodeId,
          text: `${updatedNode.nodeId} acknowledged on dashboard`
        });
        render();
      }
    };
  });

  document.querySelectorAll("button[data-action='clear']").forEach((btn) => {
    btn.onclick = async () => {
      const nodeId = btn.dataset.node;
      const res = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}/clear-alarm`, { method: "POST" });
      if (!res.ok) return;
      nodes = nodes.filter((node) => node.nodeId !== nodeId);
      addHistoryEvent({
        ts: new Date().toISOString(),
        event: "operator_clear",
        node: nodeId,
        text: `${nodeId} removed from dashboard`
      });
      render();
    };
  });
}

function upsertImage(image) {
  const idx = images.findIndex((existing) => existing.id === image.id);
  if (idx >= 0) {
    images[idx] = image;
  } else {
    images.unshift(image);
  }
  images.sort((a, b) => b.receivedAt - a.receivedAt);
  images = images.slice(0, 30);
}

function attachImageFallback() {
  if (!nodes.length || !images.length) return;

  /*
   * Keep this fallback deliberately conservative. With multiple nodes, only a
   * filename containing the node ID is auto-attached; otherwise an image could
   * be shown against the wrong trap.
   */
  for (const node of nodes) {
    if (node.latestImage?.url) continue;

    const byName = images.find((image) =>
      image.filename.toUpperCase().includes(node.nodeId.toUpperCase())
    );
    if (byName) {
      node.latestImage = byName;
      continue;
    }

    if (nodes.length === 1) {
      node.latestImage = images[0];
    }
  }
}

function getNodeState(node) {
  if (node.alarmActive) {
    if (node.alarmAcknowledged) {
      return { key: "red", label: "ACKNOWLEDGED", detail: "Trap alarm acknowledged", symbol: "!" };
    }
    return { key: "red", label: "ALARM", detail: "Trap triggered", symbol: "!" };
  }
  if (node.health === "green") {
    return { key: "green", label: "NORMAL", detail: "System healthy", symbol: "OK" };
  }
  if (node.health === "yellow") {
    return { key: "yellow", label: "MISSING HEARTBEAT", detail: "Check radio link", symbol: "!" };
  }
  return { key: "yellow", label: "MISSING HEARTBEAT", detail: "No recent response", symbol: "!" };
}

function sortNodes(a, b) {
  /*
   * Operators need the problem cases at the top of the 7 inch screen. Alarms
   * sort first, missing heartbeat second, healthy nodes last.
   */
  const score = (node) => {
    if (node.alarmActive) return 0;
    if (node.health === "yellow" || node.health === "red") return 1;
    return 2;
  };
  return score(a) - score(b) || a.nodeId.localeCompare(b.nodeId);
}

function getBattery(node) {
  const raw = node.telemetry?.batteryPercent ?? node.telemetry?.battery ?? node.telemetry?.batt;
  if (raw === undefined || raw === null || raw === "") {
    return { percent: "-", bars: "" };
  }
  const percent = clamp(Number(raw), 0, 100);
  const filled = Math.max(1, Math.ceil(percent / 20));
  return { percent: `${Math.round(percent)}%`, bars: `Level ${filled}/5` };
}

function getSignal(node) {
  const dbm = node.telemetry?.signalDbm ?? node.telemetry?.rssi ?? node.telemetry?.signal;
  const snr = node.telemetry?.snrDb ?? node.telemetry?.snr;
  const left = dbm === undefined ? "-- dBm" : `${dbm} dBm`;
  const right = snr === undefined ? "-- dB" : `${snr} dB`;
  return `${left} / ${right}`;
}

function getLocation(node) {
  const lat = node.telemetry?.lat ?? node.telemetry?.latitude;
  const lon = node.telemetry?.lon ?? node.telemetry?.longitude;
  const label = node.telemetry?.location ?? node.telemetry?.place ?? "Field node";
  if (lat !== undefined && lon !== undefined) {
    return { primary: `${lat}, ${lon}`, secondary: label };
  }
  return { primary: label, secondary: "" };
}

function formatImageStatus(node) {
  if (node.sstvImageStatus === "received") return "Received";
  if (node.sstvImageStatus === "waiting") return "Waiting";
  if (node.sstvImageStatus === "missing") return "Missing";
  return "Idle";
}

function renderFooter() {
  const alarms = nodes.filter((node) => node.alarmActive).length;
  systemStatus.textContent = alarms ? "ALARM" : "OK";
  systemStatus.className = alarms ? "bad" : "good";
  uptimeValue.textContent = formatDuration(Date.now() - startedAt);
  cpuValue.textContent = "--";
  tempValue.textContent = "--";
  storageValue.textContent = "--";
}

function formatUtcTime(value) {
  if (!value) return "--:--:-- UTC";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--:-- UTC";
  return `${date.toISOString().slice(11, 19)} UTC`;
}

function formatDuration(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function clamp(value, min, max) {
  if (!Number.isFinite(value)) return 0;
  return Math.min(max, Math.max(min, value));
}

function playAlarmTone() {
  try {
    /*
     * Browser audio must be created from a user-facing page context. Keep the
     * tone short and quiet so it draws attention without masking radio/audio
     * diagnostics from SparkSDR or JS8Call.
     */
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }

    const osc = audioContext.createOscillator();
    const gain = audioContext.createGain();
    osc.type = "square";
    osc.frequency.value = 880;
    gain.gain.value = 0.05;
    osc.connect(gain);
    gain.connect(audioContext.destination);
    osc.start();
    osc.stop(audioContext.currentTime + 0.35);
  } catch (err) {
    console.error("Alarm sound failed:", err);
  }
}

silenceBtn.addEventListener("click", () => {
  alarmMuted = true;
  alarmBanner.classList.add("hidden");
});

closeImageBtn.addEventListener("click", () => {
  imageDialog.close();
});

imageDialog.addEventListener("click", (event) => {
  if (event.target === imageDialog) {
    imageDialog.close();
  }
});

menuButton.addEventListener("click", (event) => {
  event.stopPropagation();
  const isOpen = !windowMenu.classList.contains("hidden");
  windowMenu.classList.toggle("hidden", isOpen);
  menuButton.setAttribute("aria-expanded", String(!isOpen));
});

windowMenu.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-window-action]");
  if (!button) return;

  const action = button.dataset.windowAction;
  windowMenu.classList.add("hidden");
  menuButton.setAttribute("aria-expanded", "false");

  if (action === "maximize" && document.documentElement.requestFullscreen) {
    try {
      await document.documentElement.requestFullscreen();
    } catch (_err) {
      /* The backend window-manager action below is the fallback. */
    }
  }

  try {
    const res = await fetch(`/api/window/${encodeURIComponent(action)}`, { method: "POST" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      addHistoryEvent({
        ts: new Date().toISOString(),
        event: "window_action_failed",
        text: body.error || `${action} failed`
      });
    }
  } catch (err) {
    addHistoryEvent({
      ts: new Date().toISOString(),
      event: "window_action_failed",
      text: err.message || `${action} failed`
    });
  }
});

document.addEventListener("click", () => {
  windowMenu.classList.add("hidden");
  menuButton.setAttribute("aria-expanded", "false");
});

timeSyncBtn.addEventListener("click", async () => {
  timeSyncBtn.classList.add("working");
  try {
    const res = await fetch("/api/time/resync", { method: "POST" });
    const body = await res.json().catch(() => ({}));
    addHistoryEvent({
      ts: new Date().toISOString(),
      event: res.ok ? "gps_time_sync" : "gps_time_sync_failed",
      text: res.ok
        ? `Control node time resynchronised from GPS: ${body.gpsTime}`
        : (body.error || "GPS time resync failed")
    });
  } catch (err) {
    addHistoryEvent({
      ts: new Date().toISOString(),
      event: "gps_time_sync_failed",
      text: err.message || "GPS time resync failed"
    });
  } finally {
    timeSyncBtn.classList.remove("working");
    if (activeView === "history") renderHistory();
  }
});

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}
