const CAMERA_NAMES = ["left", "front", "right"];

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js").catch((error) => {
      console.warn("Service worker ishlamadi", error);
    });
  });
}

const state = {
  speedLimit: 120,
  activeButtons: new Set(),
  availableCameras: new Set(),
  availablePumpZones: new Set(),
  focusedCamera: null,
  commandSeq: 0,
  commandTtlMs: 1200,
  serverClockOffsetMs: 0,
  activePage: "operator",
  autonomyRunning: false,
  turnBusy: false,
  manualSprayActive: false,
  manualSprayDesired: false,
};

const TURN_FACTOR = 1.15;
const DRIVE_KEEPALIVE_MS = 250;
const DEFAULT_COMMAND_TTL_MS = 1200;
const COMMAND_TIMEOUT_GRACE_MS = 250;
const MANUAL_SPRAY_KEEPALIVE_MS = 350;
const TURN_SETTLE_MS = 180;
const DEFAULT_SEGMENTS = [
  { label: "Chel ustida oldinga", left: 0.55, right: 0.55, meters: 7.0 },
  { label: "Joyida burilish", left: -0.45, right: 0.45, seconds: 1.1 },
];
let driveHoldTimer = null;
let manualSprayHeartbeatTimer = null;
const manualSprayPointerIds = new Set();

const elements = {
  esp32Badge: document.getElementById("esp32Badge"),
  motionBadge: document.getElementById("motionBadge"),
  modeBadge: document.getElementById("modeBadge"),
  operatorPage: document.getElementById("operatorPage"),
  autonomyPage: document.getElementById("autonomyPage"),
  diagnosticsPage: document.getElementById("diagnosticsPage"),
  operatorPageButton: document.getElementById("operatorPageButton"),
  autonomyPageButton: document.getElementById("autonomyPageButton"),
  diagnosticsPageButton: document.getElementById("diagnosticsPageButton"),
  cameraPanel: document.getElementById("cameraPanel"),
  cameraCards: Array.from(document.querySelectorAll(".camera-card")),
  speedValue: document.getElementById("speedValue"),
  speedSlider: document.getElementById("speedSlider"),
  manualSprayButton: document.getElementById("manualSprayButton"),
  stopButton: document.getElementById("stopButton"),
  autoSprayToggle: document.getElementById("autoSprayToggle"),
  turnLeftButton: document.getElementById("turnLeftButton"),
  turnRightButton: document.getElementById("turnRightButton"),
  turnLeft90Button: document.getElementById("turnLeft90Button"),
  turnRight90Button: document.getElementById("turnRight90Button"),
  forwardButton: document.getElementById("forwardButton"),
  backwardButton: document.getElementById("backwardButton"),
  warningsList: document.getElementById("warningsList"),
  diagEsp32: document.getElementById("diagEsp32"),
  esp32Metric: document.getElementById("esp32Metric"),
  speedMetric: document.getElementById("speedMetric"),
  autoSprayMetric: document.getElementById("autoSprayMetric"),
  lastSprayMetric: document.getElementById("lastSprayMetric"),
  leftPumpState: document.getElementById("leftPumpState"),
  frontPumpState: document.getElementById("frontPumpState"),
  rightPumpState: document.getElementById("rightPumpState"),
  leftCameraBadge: document.getElementById("leftCameraBadge"),
  frontCameraBadge: document.getElementById("frontCameraBadge"),
  rightCameraBadge: document.getElementById("rightCameraBadge"),
  leftCameraMeta: document.getElementById("leftCameraMeta"),
  frontCameraMeta: document.getElementById("frontCameraMeta"),
  rightCameraMeta: document.getElementById("rightCameraMeta"),
  leftCameraStream: document.getElementById("leftCameraStream"),
  frontCameraStream: document.getElementById("frontCameraStream"),
  rightCameraStream: document.getElementById("rightCameraStream"),
  missionForm: document.getElementById("missionForm"),
  missionName: document.getElementById("missionName"),
  missionSpeed: document.getElementById("missionSpeed"),
  missionSpeedValue: document.getElementById("missionSpeedValue"),
  missionSegments: document.getElementById("missionSegments"),
  previewPlanButton: document.getElementById("previewPlanButton"),
  startPlanButton: document.getElementById("startPlanButton"),
  stopPlanButton: document.getElementById("stopPlanButton"),
  planStatusMetric: document.getElementById("planStatusMetric"),
  planProgressMetric: document.getElementById("planProgressMetric"),
  planRemainingMetric: document.getElementById("planRemainingMetric"),
  planCurrentMetric: document.getElementById("planCurrentMetric"),
  planPreview: document.getElementById("planPreview"),
  pumpCards: Array.from(document.querySelectorAll(".spray-card")),
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function setRangeProgress(element, value = Number(element.value), max = Number(element.max) || 100) {
  const percent = `${clamp((Number(value) / max) * 100, 0, 100)}%`;
  element.style.setProperty("--range-progress", percent);
}

function cameraCardFor(name) {
  return elements.cameraCards.find((card) => card.dataset.cameraCard === name) || null;
}

function renderCameraFocus() {
  const focusedName = state.focusedCamera;
  elements.cameraPanel.classList.toggle("focus-mode", Boolean(focusedName));
  elements.cameraPanel.classList.remove("focus-left", "focus-front", "focus-right");
  if (focusedName) {
    elements.cameraPanel.classList.add(`focus-${focusedName}`);
  }

  elements.cameraCards.forEach((card) => {
    const name = card.dataset.cameraCard;
    const title = card.querySelector("h2")?.textContent || "Kamera";
    const isDisabled = card.classList.contains("camera-disabled");
    const isFocused = focusedName === name;
    const isDimmed = Boolean(focusedName) && !isFocused;
    card.classList.toggle("focused-camera", isFocused);
    card.classList.toggle("dimmed-camera", isDimmed);
    card.setAttribute("aria-pressed", String(isFocused));
    card.setAttribute(
      "aria-label",
      isDisabled
        ? `${title} hozircha mavjud emas`
        : isFocused
          ? `${title} kattalashtirilgan. Oddiy ko'rinishga qaytish uchun qayta bosing.`
          : `${title} ni kattalashtirish`
    );
  });
}

function toggleFocusedCamera(name) {
  const card = cameraCardFor(name);
  if (!card || card.classList.contains("camera-disabled")) return;
  state.focusedCamera = state.focusedCamera === name ? null : name;
  renderCameraFocus();
}

function setCameraAvailability(name, available) {
  const card = cameraCardFor(name);
  if (!card) return;
  card.classList.toggle("camera-disabled", !available);
  card.tabIndex = available ? 0 : -1;
  card.setAttribute("aria-disabled", String(!available));
  if (!available && state.focusedCamera === name) {
    state.focusedCamera = null;
  }
}

function throttle(callback, wait) {
  let lastRun = 0;
  let timeoutId = null;
  let lastArgs = null;
  return (...args) => {
    lastArgs = args;
    const now = Date.now();
    const remaining = wait - (now - lastRun);
    if (remaining <= 0) {
      if (timeoutId) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }
      lastRun = now;
      callback(...lastArgs);
    } else if (!timeoutId) {
      timeoutId = setTimeout(() => {
        lastRun = Date.now();
        timeoutId = null;
        callback(...lastArgs);
      }, remaining);
    }
  };
}

async function postJson(url, payload = {}) {
  const ttlMs = Number(state.commandTtlMs || DEFAULT_COMMAND_TTL_MS);
  const stampedPayload = stampRealtimeCommand(payload, ttlMs);
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => {
    controller.abort();
  }, ttlMs + COMMAND_TIMEOUT_GRACE_MS);

  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(stampedPayload),
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (error) {
    return {
      ok: false,
      error: error?.name === "AbortError" ? "request_timeout" : "network_error",
      detail: String(error),
    };
  } finally {
    window.clearTimeout(timeoutId);
  }

  let body = await response.json().catch(() => ({
    ok: false,
    error: "bad_response",
  }));
  if (!body || typeof body !== "object") {
    body = { ok: response.ok, value: body };
  }
  if (!response.ok) body.http_status = response.status;
  return body;
}

function serverNowMs() {
  return Math.round(Date.now() + state.serverClockOffsetMs);
}

function stampRealtimeCommand(payload, ttlMs) {
  const sentAtMs = serverNowMs();
  return {
    ...payload,
    seq: payload.seq ?? nextCommandSeq(),
    client_sent_at_ms: sentAtMs,
    expires_at_ms: sentAtMs + ttlMs,
    ttl_ms: ttlMs,
  };
}

function nextCommandSeq() {
  state.commandSeq += 1;
  return state.commandSeq;
}

function canSendManualDrive() {
  return !state.turnBusy && !state.autonomyRunning;
}

function delay(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function setPage(pageName, shouldStop = false) {
  const nextPage = ["autonomy", "diagnostics"].includes(pageName) ? pageName : "operator";
  state.activePage = nextPage;
  document.body.classList.toggle("operator-layout", nextPage === "operator");

  elements.operatorPage.hidden = nextPage !== "operator";
  elements.autonomyPage.hidden = nextPage !== "autonomy";
  elements.diagnosticsPage.hidden = nextPage !== "diagnostics";
  elements.operatorPage.classList.toggle("active-page", nextPage === "operator");
  elements.autonomyPage.classList.toggle("active-page", nextPage === "autonomy");
  elements.diagnosticsPage.classList.toggle("active-page", nextPage === "diagnostics");
  elements.operatorPageButton.classList.toggle("active-tab", nextPage === "operator");
  elements.autonomyPageButton.classList.toggle("active-tab", nextPage === "autonomy");
  elements.diagnosticsPageButton.classList.toggle("active-tab", nextPage === "diagnostics");

  if (shouldStop && nextPage !== "operator") {
    void clearDriveAndStop();
  }
}

elements.operatorPageButton.addEventListener("click", () => {
  history.replaceState(null, "", "#operator");
  setPage("operator");
});

elements.autonomyPageButton.addEventListener("click", () => {
  history.replaceState(null, "", "#autonomy");
  setPage("autonomy", true);
});

elements.diagnosticsPageButton.addEventListener("click", () => {
  history.replaceState(null, "", "#diagnostics");
  setPage("diagnostics", true);
});

window.addEventListener("hashchange", () => {
  const pageName = location.hash === "#diagnostics"
    ? "diagnostics"
    : location.hash === "#autonomy"
      ? "autonomy"
      : "operator";
  setPage(pageName, true);
});

function isEditableTarget(target) {
  return target instanceof HTMLElement && Boolean(target.closest("input, textarea"));
}

function blockSelectionAndCopyUI() {
  document.addEventListener("contextmenu", (event) => {
    if (!isEditableTarget(event.target)) {
      event.preventDefault();
    }
  }, { capture: true });

  document.addEventListener("selectstart", (event) => {
    if (!isEditableTarget(event.target)) {
      event.preventDefault();
    }
  }, { capture: true });

  document.addEventListener("dragstart", (event) => {
    if (!isEditableTarget(event.target)) {
      event.preventDefault();
    }
  }, { capture: true });
}

function getAxes() {
  const horizontal =
    Number(state.activeButtons.has("right")) - Number(state.activeButtons.has("left"));
  const vertical =
    Number(state.activeButtons.has("forward")) - Number(state.activeButtons.has("backward"));
  return { horizontal, vertical };
}

function getDriveValues() {
  const { horizontal, vertical } = getAxes();
  const left = clamp(vertical + horizontal * TURN_FACTOR, -1, 1);
  const right = clamp(vertical - horizontal * TURN_FACTOR, -1, 1);
  return { left, right, horizontal, vertical };
}

function motionLabel(horizontal, vertical) {
  if (horizontal === 0 && vertical === 0) return "stop";
  if (vertical > 0 && horizontal === 0) return "oldinga";
  if (vertical < 0 && horizontal === 0) return "orqaga";
  if (horizontal < 0 && vertical === 0) return "chapga";
  if (horizontal > 0 && vertical === 0) return "o'ngga";
  if (vertical > 0 && horizontal < 0) return "oldinga + chapga";
  if (vertical > 0 && horizontal > 0) return "oldinga + o'ngga";
  if (vertical < 0 && horizontal < 0) return "orqaga + chapga";
  return "orqaga + o'ngga";
}

async function sendDrivePayload(payload) {
  if (!canSendManualDrive()) return;
  try {
    await postJson("/api/control/tank", payload);
  } catch (error) {
    elements.motionBadge.textContent = `Harakat: server xato`;
  }
}

const sendDriveKeepalive = throttle(() => {
  const { left, right, horizontal, vertical } = getDriveValues();
  elements.motionBadge.textContent = `Harakat: ${motionLabel(horizontal, vertical)}`;
  void sendDrivePayload({
    left,
    right,
    speed_limit: state.speedLimit,
    seq: nextCommandSeq(),
  });
}, 90);

async function sendCurrentDriveState() {
  if (!canSendManualDrive()) return;
  const { left, right, horizontal, vertical } = getDriveValues();
  elements.motionBadge.textContent = `Harakat: ${motionLabel(horizontal, vertical)}`;

  if (horizontal === 0 && vertical === 0) {
    await postJson("/api/control/stop", { seq: nextCommandSeq() });
    return;
  }

  await sendDrivePayload({
    left,
    right,
    speed_limit: state.speedLimit,
    seq: nextCommandSeq(),
  });
}

function renderSpeed() {
  elements.speedValue.textContent = String(state.speedLimit);
  elements.speedMetric.textContent = String(state.speedLimit);
  setRangeProgress(elements.speedSlider, state.speedLimit, 255);
}

function markButtonActive() {
  elements.turnLeftButton.classList.toggle("active-drive", state.activeButtons.has("left"));
  elements.turnRightButton.classList.toggle("active-drive", state.activeButtons.has("right"));
  elements.forwardButton.classList.toggle("active-drive", state.activeButtons.has("forward"));
  elements.backwardButton.classList.toggle("active-drive", state.activeButtons.has("backward"));
}

function releaseDirection(key) {
  if (state.activeButtons.delete(key)) {
    markButtonActive();
    syncDriveHoldTimer();
    void sendCurrentDriveState();
  }
}

function attachDriveButton(element, key) {
  const activePointers = new Set();

  element.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    if (!canSendManualDrive()) return;
    activePointers.add(event.pointerId);
    state.activeButtons.add(key);
    element.setPointerCapture(event.pointerId);
    markButtonActive();
    syncDriveHoldTimer();
    void sendCurrentDriveState();
  });

  const release = (event) => {
    activePointers.delete(event.pointerId);
    if (activePointers.size === 0) releaseDirection(key);
  };

  element.addEventListener("pointerup", release);
  element.addEventListener("pointercancel", release);
  element.addEventListener("lostpointercapture", release);
}

function syncDriveHoldTimer() {
  if (state.activeButtons.size > 0) {
    if (!driveHoldTimer) {
      driveHoldTimer = setInterval(() => {
        void sendDriveKeepalive();
      }, DRIVE_KEEPALIVE_MS);
    }
    return;
  }

  if (driveHoldTimer) {
    clearInterval(driveHoldTimer);
    driveHoldTimer = null;
  }
}

function clearDriveAndStop({ force = false } = {}) {
  state.activeButtons.clear();
  markButtonActive();
  syncDriveHoldTimer();
  elements.motionBadge.textContent = "Harakat: stop";
  if (!force && !canSendManualDrive()) {
    return Promise.resolve({ ok: true, skipped: "autonomy" });
  }
  return postJson("/api/control/stop", { seq: nextCommandSeq() });
}

function setTurnBusy(isBusy) {
  state.turnBusy = isBusy;
  syncTurnButtons();
}

function syncTurnButtons() {
  const disabled = state.turnBusy || state.autonomyRunning;
  elements.turnLeft90Button.disabled = disabled;
  elements.turnRight90Button.disabled = disabled;
}

async function triggerTurn90(direction) {
  if (state.turnBusy) return;
  setTurnBusy(true);
  try {
    await clearDriveAndStop({ force: true });
    await delay(TURN_SETTLE_MS);
    const response = await postJson("/api/control/turn90", { direction });
    if (!response.ok) {
      elements.motionBadge.textContent = `Harakat: ${response.detail || response.error || "turn xato"}`;
      return;
    }
    state.autonomyRunning = true;
    syncTurnButtons();
    elements.motionBadge.textContent = `Harakat: 90° ${direction === "left" ? "chap" : "o'ng"}`;
  } finally {
    window.setTimeout(() => setTurnBusy(false), 250);
  }
}

attachDriveButton(elements.turnLeftButton, "left");
attachDriveButton(elements.turnRightButton, "right");
attachDriveButton(elements.forwardButton, "forward");
attachDriveButton(elements.backwardButton, "backward");

window.addEventListener("blur", () => {
  void clearDriveAndStop();
  manualSprayPointerIds.clear();
  void setManualSpray(false, { force: true });
});

elements.stopButton.addEventListener("click", async () => {
  await Promise.all([clearDriveAndStop({ force: true }), setManualSpray(false, { force: true })]);
});

elements.turnLeft90Button.addEventListener("click", async () => {
  await triggerTurn90("left");
});

elements.turnRight90Button.addEventListener("click", async () => {
  await triggerTurn90("right");
});

elements.speedSlider.addEventListener("input", () => {
  state.speedLimit = Number(elements.speedSlider.value);
  renderSpeed();
});

elements.speedSlider.addEventListener("change", async () => {
  await postJson("/api/control/speed", { speed_limit: state.speedLimit });
});

elements.autoSprayToggle.addEventListener("change", async () => {
  await postJson("/api/control/auto-spray", { enabled: elements.autoSprayToggle.checked });
});

function renderManualSprayButton(enabled) {
  elements.manualSprayButton.classList.toggle("spraying", enabled);
  elements.manualSprayButton.setAttribute("aria-pressed", String(enabled));
}

function syncManualSprayHeartbeat() {
  if (state.manualSprayDesired) {
    if (!manualSprayHeartbeatTimer) {
      manualSprayHeartbeatTimer = window.setInterval(() => {
        if (state.manualSprayDesired) {
          void sendManualSprayCommand(true, { heartbeat: true });
        }
      }, MANUAL_SPRAY_KEEPALIVE_MS);
    }
    return;
  }

  if (manualSprayHeartbeatTimer) {
    window.clearInterval(manualSprayHeartbeatTimer);
    manualSprayHeartbeatTimer = null;
  }
}

async function sendManualSprayCommand(enabled, { heartbeat = false } = {}) {
  const response = await postJson("/api/control/spray", { enabled });
  if (!response.ok) {
    if (!heartbeat) {
      console.warn("Qo'lda sepish buyrug'i yuborilmadi", response);
    }
    return response;
  }

  if (!response.ignored && state.manualSprayDesired === enabled) {
    state.manualSprayActive = enabled;
    renderManualSprayButton(enabled);
  }
  if (!heartbeat && !response.ignored) {
    elements.motionBadge.textContent = enabled
      ? "Harakat: qo'lda sepish"
      : "Harakat: manual";
  }
  return response;
}

function setManualSpray(enabled, { force = false } = {}) {
  if (!force && state.manualSprayDesired === enabled) {
    return Promise.resolve({ ok: true, skipped: "same_state" });
  }
  state.manualSprayDesired = enabled;
  state.manualSprayActive = enabled;
  renderManualSprayButton(enabled);
  syncManualSprayHeartbeat();
  return sendManualSprayCommand(enabled);
}

elements.manualSprayButton.addEventListener("pointerdown", (event) => {
  if (event.button !== undefined && event.button !== 0) return;
  event.preventDefault();
  manualSprayPointerIds.add(event.pointerId);
  elements.manualSprayButton.setPointerCapture?.(event.pointerId);
  void setManualSpray(true);
});

function releaseManualSprayPointer(event) {
  const hadPointer = manualSprayPointerIds.delete(event.pointerId);
  if (!hadPointer || manualSprayPointerIds.size > 0) return;
  void setManualSpray(false, { force: true });
}

elements.manualSprayButton.addEventListener("pointerup", (event) => {
  releaseManualSprayPointer(event);
});

elements.manualSprayButton.addEventListener("pointercancel", (event) => {
  releaseManualSprayPointer(event);
});

elements.manualSprayButton.addEventListener("lostpointercapture", (event) => {
  releaseManualSprayPointer(event);
});

function renderMissionSpeed() {
  elements.missionSpeedValue.textContent = elements.missionSpeed.value;
  setRangeProgress(elements.missionSpeed, Number(elements.missionSpeed.value), 255);
}

function buildMissionPayload() {
  let parsed;
  try {
    parsed = JSON.parse(elements.missionSegments.value);
  } catch (error) {
    throw new Error("Segmentlar JSON formati noto'g'ri.");
  }

  const segments = Array.isArray(parsed) ? parsed : parsed.segments;
  if (!Array.isArray(segments) || segments.length === 0) {
    throw new Error("Kamida bitta segment kerak.");
  }

  return {
    name: elements.missionName.value.trim() || "Agro Mission",
    speed_limit: Number(elements.missionSpeed.value),
    segments,
  };
}

function showPlanMessage(message, isError = false) {
  elements.planPreview.textContent = message;
  elements.planPreview.classList.toggle("error", isError);
}

function renderPlanResponse(response) {
  if (!response.ok) {
    showPlanMessage(response.detail || response.error || "Reja qabul qilinmadi.", true);
    return;
  }

  const plan = response.plan || response;
  showPlanMessage(JSON.stringify(plan, null, 2), false);
}

async function previewMissionPlan() {
  try {
    const payload = buildMissionPayload();
    const response = await postJson("/api/autonomy/plan", payload);
    renderPlanResponse(response);
  } catch (error) {
    showPlanMessage(error.message, true);
  }
}

async function startMissionPlan() {
  try {
    const payload = buildMissionPayload();
    const response = await postJson("/api/autonomy/start", payload);
    renderPlanResponse(response);
  } catch (error) {
    showPlanMessage(error.message, true);
  }
}

async function stopMissionPlan() {
  const response = await postJson("/api/autonomy/stop", {});
  renderPlanResponse(response);
}

elements.missionSegments.value = JSON.stringify(DEFAULT_SEGMENTS, null, 2);
renderMissionSpeed();

elements.missionSpeed.addEventListener("input", renderMissionSpeed);
elements.previewPlanButton.addEventListener("click", previewMissionPlan);
elements.startPlanButton.addEventListener("click", startMissionPlan);
elements.stopPlanButton.addEventListener("click", stopMissionPlan);

document.querySelectorAll(".test-pump-button").forEach((button) => {
  button.addEventListener("click", async () => {
    const side = button.dataset.pump;
    button.disabled = true;
    await postJson("/api/control/pump", { side, enabled: true, auto_off_ms: 350 });
    window.setTimeout(() => {
      button.disabled = false;
    }, 350);
  });
});

function setBadge(element, isOnline, onlineText, offlineText) {
  element.classList.toggle("online", Boolean(isOnline));
  element.classList.toggle("offline", !isOnline);
  element.textContent = isOnline ? onlineText : offlineText;
}

function setCameraDisabled(name) {
  const mapping = {
    left: [elements.leftCameraBadge, elements.leftCameraMeta, elements.leftCameraStream],
    front: [elements.frontCameraBadge, elements.frontCameraMeta, elements.frontCameraStream],
    right: [elements.rightCameraBadge, elements.rightCameraMeta, elements.rightCameraStream],
  };
  const [badge, meta, stream] = mapping[name];
  setCameraAvailability(name, false);
  setBadge(badge, false, "online", "disabled");
  meta.textContent = "Config ichida yoqilmagan.";
  stream.removeAttribute("src");
}

function configureCameraCards(cameraList) {
  state.availableCameras = new Set(cameraList.map((camera) => camera.name));
  CAMERA_NAMES.forEach((name) => {
    const stream = elements[`${name}CameraStream`];
    if (state.availableCameras.has(name)) {
      setCameraAvailability(name, true);
      if (!stream.src) stream.src = stream.dataset.stream;
    } else {
      setCameraDisabled(name);
    }
  });
  renderCameraFocus();
}

function configurePumpCards(pumpZones) {
  state.availablePumpZones = new Set(pumpZones);
  elements.pumpCards.forEach((card) => {
    const zone = card.dataset.zone;
    const isVisible = state.availablePumpZones.has(zone);
    card.hidden = !isVisible;
  });
}

function cameraMeta(camera, fallback) {
  if (!camera) return fallback;
  if (!camera.online) return camera.error || "Offline";
  const detection = camera.last_detection;
  if (!detection) return `FPS ${camera.fps} | det ${camera.detections}`;
  const centered = detection.centered ? "CENTER" : "offset";
  const label = detection.label || "flower";
  const source = detection.source ? ` | ${detection.source}` : "";
  return `FPS ${camera.fps} | det ${camera.detections} | ${label} | ${centered} ${detection.offset_px}px | conf ${detection.confidence}${source}`;
}

function renderPumpStates(pumps) {
  const zones = state.availablePumpZones.size
    ? Array.from(state.availablePumpZones)
    : Object.keys(pumps || {});
  zones.forEach((zone) => {
    const element = elements[`${zone}PumpState`];
    if (!element) return;
    const enabled = Boolean(pumps?.[zone]);
    element.textContent = enabled ? "ON" : "OFF";
    element.classList.toggle("pump-on", enabled);
  });
}

function renderWarnings(items) {
  elements.warningsList.replaceChildren(
    ...items.map((item) => {
      const listItem = document.createElement("li");
      listItem.textContent = item;
      return listItem;
    })
  );
}

function renderDiagnostics(esp32, measurements, spray) {
  const rows = [
    `Transport: ${esp32.transport || "-"}`,
    `Base URL: ${esp32.base_url || "-"}`,
    `Serial port: ${esp32.serial_port || "-"}`,
    `Firmware: ${esp32.firmware_mode || "-"}`,
    `Reference margin: ${measurements.lane_margin_cm ?? "-"} sm`,
    `Spray count: ${spray.trigger_count || 0}`,
  ];
  elements.diagEsp32.replaceChildren(
    ...rows.map((row) => {
      const paragraph = document.createElement("p");
      paragraph.textContent = row;
      return paragraph;
    })
  );
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    const config = await response.json();
    if (Number.isFinite(Number(config.server_time_ms))) {
      state.serverClockOffsetMs = Number(config.server_time_ms) - Date.now();
    }
    if (Number.isFinite(Number(config.command_ttl_ms))) {
      state.commandTtlMs = Number(config.command_ttl_ms);
    }
    configureCameraCards(config.cameras || []);
    configurePumpCards(config.auto_spray?.spray_zones || []);
  } catch (error) {
    console.error("Config yuklanmadi", error);
  }
}

async function refreshState() {
  try {
    const response = await fetch("/api/state");
    const snapshot = await response.json();
    const measurements = snapshot.measurements || {};
    const esp32 = snapshot.esp32 || {};
    const control = snapshot.control || {};
    const spray = snapshot.spray || {};
    const autonomy = snapshot.autonomy || {};
    const cameras = snapshot.cameras || {};
    const lastSprayTargets = Array.isArray(spray.last_pumps) && spray.last_pumps.length
      ? spray.last_pumps.join(" + ")
      : spray.last_pump || "-";
    state.autonomyRunning = Boolean(autonomy.running);
    syncTurnButtons();

    setBadge(
      elements.esp32Badge,
      esp32.online,
      `ESP32: online | ${esp32.firmware_mode}`,
      `ESP32: offline | ${esp32.last_error || "javob yo'q"}`
    );
    elements.esp32Metric.textContent = esp32.online ? "online" : "offline";
    elements.modeBadge.textContent = `Mode: ${autonomy.running ? "autonomy" : control.mode || "manual"}`;
    elements.autoSprayMetric.textContent = control.auto_spray ? "ON" : "OFF";
    elements.lastSprayMetric.textContent = `${lastSprayTargets} | ${spray.last_trigger_at || "-"}`;
    elements.motionBadge.textContent = autonomy.running
      ? `Harakat: ${autonomy.current_label || autonomy.status || "autonomy"}`
      : `Harakat: ${control.last_command || "stop"}`;

    CAMERA_NAMES.forEach((name) => {
      if (!state.availableCameras.has(name)) return;
      setBadge(elements[`${name}CameraBadge`], cameras[name]?.online, "online", "offline");
      elements[`${name}CameraMeta`].textContent = cameraMeta(cameras[name], `${name} kamera`);
    });

    renderPumpStates(snapshot.pumps || {});

    elements.planStatusMetric.textContent = autonomy.status || "idle";
    elements.planProgressMetric.textContent = `${Math.round(Number(autonomy.progress || 0) * 100)}%`;
    elements.planRemainingMetric.textContent = `${Number(autonomy.remaining_seconds || 0).toFixed(1)}s`;
    elements.planCurrentMetric.textContent = autonomy.current_label || "-";

    renderWarnings(snapshot.warnings?.length ? snapshot.warnings : ["Ogohlantirish yo'q"]);
    renderDiagnostics(esp32, measurements, spray);

    elements.autoSprayToggle.checked = Boolean(control.auto_spray);
    if (manualSprayPointerIds.size === 0) {
      state.manualSprayActive = Boolean(control.manual_spray);
      state.manualSprayDesired = state.manualSprayActive;
      syncManualSprayHeartbeat();
      renderManualSprayButton(state.manualSprayActive);
    }
    state.speedLimit = Number(control.speed_limit || state.speedLimit);
    elements.speedSlider.value = String(state.speedLimit);
    renderSpeed();
  } catch (error) {
    elements.esp32Badge.textContent = `Server xato: ${error}`;
    elements.esp32Metric.textContent = "server xato";
  }
}

renderSpeed();
elements.cameraCards.forEach((card) => {
  const name = card.dataset.cameraCard;
  card.addEventListener("click", () => {
    toggleFocusedCamera(name);
  });
  card.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    toggleFocusedCamera(name);
  });
});
blockSelectionAndCopyUI();
syncTurnButtons();
renderCameraFocus();
setPage(
  location.hash === "#diagnostics"
    ? "diagnostics"
    : location.hash === "#autonomy"
      ? "autonomy"
      : "operator"
);
loadConfig().finally(refreshState);
setInterval(refreshState, 1000);
