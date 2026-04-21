const CAMERA_NAMES = ["left", "front", "right"];
const SPRAY_ZONES = ["left", "front", "right"];

const state = {
  speedLimit: 120,
  activeButtons: new Set(),
  availableCameras: new Set(),
  commandSeq: 0,
  activePage: "operator",
};

const TURN_FACTOR = 0.7;
const DRIVE_KEEPALIVE_MS = 250;
let driveHoldTimer = null;

const elements = {
  esp32Badge: document.getElementById("esp32Badge"),
  motionBadge: document.getElementById("motionBadge"),
  modeBadge: document.getElementById("modeBadge"),
  operatorPage: document.getElementById("operatorPage"),
  diagnosticsPage: document.getElementById("diagnosticsPage"),
  operatorPageButton: document.getElementById("operatorPageButton"),
  diagnosticsPageButton: document.getElementById("diagnosticsPageButton"),
  speedValue: document.getElementById("speedValue"),
  speedSlider: document.getElementById("speedSlider"),
  stopButton: document.getElementById("stopButton"),
  autoSprayToggle: document.getElementById("autoSprayToggle"),
  mainEsp32Metric: document.getElementById("mainEsp32Metric"),
  mainEsp32Detail: document.getElementById("mainEsp32Detail"),
  mainMotionMetric: document.getElementById("mainMotionMetric"),
  mainModeMetric: document.getElementById("mainModeMetric"),
  turnLeftButton: document.getElementById("turnLeftButton"),
  turnRightButton: document.getElementById("turnRightButton"),
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
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
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
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

function nextCommandSeq() {
  state.commandSeq += 1;
  return state.commandSeq;
}

function setPage(pageName, shouldStop = false) {
  const nextPage = pageName === "diagnostics" ? "diagnostics" : "operator";
  state.activePage = nextPage;

  elements.operatorPage.hidden = nextPage !== "operator";
  elements.diagnosticsPage.hidden = nextPage !== "diagnostics";
  elements.operatorPage.classList.toggle("active-page", nextPage === "operator");
  elements.diagnosticsPage.classList.toggle("active-page", nextPage === "diagnostics");
  elements.operatorPageButton.classList.toggle("active-tab", nextPage === "operator");
  elements.diagnosticsPageButton.classList.toggle("active-tab", nextPage === "diagnostics");

  if (shouldStop && nextPage !== "operator") {
    void clearDriveAndStop();
  }
}

elements.operatorPageButton.addEventListener("click", () => {
  history.replaceState(null, "", "#operator");
  setPage("operator");
});

elements.diagnosticsPageButton.addEventListener("click", () => {
  history.replaceState(null, "", "#diagnostics");
  setPage("diagnostics", true);
});

window.addEventListener("hashchange", () => {
  setPage(location.hash === "#diagnostics" ? "diagnostics" : "operator", true);
});

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

function clearDriveAndStop() {
  state.activeButtons.clear();
  markButtonActive();
  syncDriveHoldTimer();
  elements.motionBadge.textContent = "Harakat: stop";
  return postJson("/api/control/stop", { seq: nextCommandSeq() });
}

attachDriveButton(elements.turnLeftButton, "left");
attachDriveButton(elements.turnRightButton, "right");
attachDriveButton(elements.forwardButton, "forward");
attachDriveButton(elements.backwardButton, "backward");

window.addEventListener("blur", () => {
  void clearDriveAndStop();
});

elements.stopButton.addEventListener("click", async () => {
  await clearDriveAndStop();
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

document.querySelectorAll(".test-pump-button").forEach((button) => {
  button.addEventListener("click", async () => {
    const side = button.dataset.pump;
    button.disabled = true;
    await postJson("/api/control/pump", { side, enabled: true });
    setTimeout(async () => {
      await postJson("/api/control/pump", { side, enabled: false });
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
  setBadge(badge, false, "online", "disabled");
  meta.textContent = "Config ichida yoqilmagan.";
  stream.removeAttribute("src");
}

function configureCameraCards(cameraList) {
  state.availableCameras = new Set(cameraList.map((camera) => camera.name));
  CAMERA_NAMES.forEach((name) => {
    const stream = elements[`${name}CameraStream`];
    if (state.availableCameras.has(name)) {
      if (!stream.src) stream.src = stream.dataset.stream;
    } else {
      setCameraDisabled(name);
    }
  });
}

function cameraMeta(camera, fallback) {
  if (!camera) return fallback;
  if (!camera.online) return camera.error || "Offline";
  const detection = camera.last_detection;
  if (!detection) return `FPS ${camera.fps} | det ${camera.detections}`;
  const centered = detection.centered ? "CENTER" : "offset";
  return `FPS ${camera.fps} | det ${camera.detections} | ${centered} ${detection.offset_px}px | conf ${detection.confidence}`;
}

function listToHtml(items) {
  return items.map((item) => `<li>${item}</li>`).join("");
}

function renderPumpStates(pumps) {
  SPRAY_ZONES.forEach((zone) => {
    const element = elements[`${zone}PumpState`];
    const enabled = Boolean(pumps?.[zone]);
    element.textContent = enabled ? "ON" : "OFF";
    element.classList.toggle("pump-on", enabled);
  });
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    const config = await response.json();
    configureCameraCards(config.cameras || []);
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
    const cameras = snapshot.cameras || {};

    setBadge(
      elements.esp32Badge,
      esp32.online,
      `ESP32: online | ${esp32.firmware_mode}`,
      `ESP32: offline | ${esp32.last_error || "javob yo'q"}`
    );
    elements.esp32Metric.textContent = esp32.online ? "online" : "offline";
    elements.modeBadge.textContent = `Mode: ${control.mode || "manual"}`;
    elements.mainEsp32Metric.textContent = esp32.online ? "online" : "offline";
    elements.mainEsp32Detail.textContent = esp32.online
      ? `${esp32.base_url || "-"} | ${esp32.firmware_mode || "-"}`
      : esp32.last_error || "javob yo'q";
    elements.mainMotionMetric.textContent = control.last_command || "stop";
    elements.mainModeMetric.textContent = `Mode: ${control.mode || "manual"} | ESP ${esp32.firmware_mode || "-"}`;
    elements.autoSprayMetric.textContent = control.auto_spray ? "ON" : "OFF";
    elements.lastSprayMetric.textContent = `${spray.last_pump || "-"} | ${spray.last_trigger_at || "-"}`;
    elements.motionBadge.textContent = `Harakat: ${control.last_command || "stop"}`;

    CAMERA_NAMES.forEach((name) => {
      if (!state.availableCameras.has(name)) return;
      setBadge(elements[`${name}CameraBadge`], cameras[name]?.online, "online", "offline");
      elements[`${name}CameraMeta`].textContent = cameraMeta(cameras[name], `${name} kamera`);
    });

    renderPumpStates(snapshot.pumps || {});

    elements.warningsList.innerHTML = listToHtml(
      snapshot.warnings?.length ? snapshot.warnings : ["Ogohlantirish yo'q"]
    );

    elements.diagEsp32.innerHTML = `
      <p>Base URL: ${esp32.base_url || "-"}</p>
      <p>Firmware: ${esp32.firmware_mode || "-"}</p>
      <p>Chel usti track zaxirasi: ${measurements.lane_margin_cm ?? "-"} sm</p>
      <p>Spray count: ${spray.trigger_count || 0}</p>
    `;

    elements.autoSprayToggle.checked = Boolean(control.auto_spray);
    state.speedLimit = Number(control.speed_limit || state.speedLimit);
    elements.speedSlider.value = String(state.speedLimit);
    renderSpeed();
  } catch (error) {
    elements.esp32Badge.textContent = `Server xato: ${error}`;
    elements.esp32Metric.textContent = "server xato";
  }
}

renderSpeed();
setPage(location.hash === "#diagnostics" ? "diagnostics" : "operator");
loadConfig().finally(refreshState);
setInterval(refreshState, 1000);
