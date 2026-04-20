const state = {
  speedLimit: 120,
  activeButtons: new Set(),
  availableCameras: new Set(),
  commandSeq: 0,
};

const TURN_FACTOR = 0.7;
const DRIVE_KEEPALIVE_MS = 250;
let driveHoldTimer = null;

const elements = {
  esp32Badge: document.getElementById("esp32Badge"),
  motionBadge: document.getElementById("motionBadge"),
  marginBadge: document.getElementById("marginBadge"),
  speedValue: document.getElementById("speedValue"),
  speedSlider: document.getElementById("speedSlider"),
  stopButton: document.getElementById("stopButton"),
  autoSprayToggle: document.getElementById("autoSprayToggle"),
  turnLeftButton: document.getElementById("turnLeftButton"),
  turnRightButton: document.getElementById("turnRightButton"),
  forwardButton: document.getElementById("forwardButton"),
  backwardButton: document.getElementById("backwardButton"),
  warningsList: document.getElementById("warningsList"),
  diagEsp32: document.getElementById("diagEsp32"),
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
  if (horizontal === 0 && vertical === 0) {
    return "stop";
  }
  if (vertical > 0 && horizontal === 0) {
    return "oldinga";
  }
  if (vertical < 0 && horizontal === 0) {
    return "orqaga";
  }
  if (horizontal < 0 && vertical === 0) {
    return "chapga";
  }
  if (horizontal > 0 && vertical === 0) {
    return "o'ngga";
  }
  if (vertical > 0 && horizontal < 0) {
    return "oldinga + chapga";
  }
  if (vertical > 0 && horizontal > 0) {
    return "oldinga + o'ngga";
  }
  if (vertical < 0 && horizontal < 0) {
    return "orqaga + chapga";
  }
  return "orqaga + o'ngga";
}

const sendDriveKeepalive = throttle(async () => {
  const { left, right, horizontal, vertical } = getDriveValues();
  elements.motionBadge.textContent = `Holat: ${motionLabel(horizontal, vertical)}`;
  await postJson("/api/control/tank", {
    left,
    right,
    speed_limit: state.speedLimit,
    seq: nextCommandSeq(),
  });
}, 90);

async function sendCurrentDriveState() {
  const { left, right, horizontal, vertical } = getDriveValues();
  elements.motionBadge.textContent = `Holat: ${motionLabel(horizontal, vertical)}`;

  if (horizontal === 0 && vertical === 0) {
    await postJson("/api/control/stop", { seq: nextCommandSeq() });
    return;
  }

  await postJson("/api/control/tank", {
    left,
    right,
    speed_limit: state.speedLimit,
    seq: nextCommandSeq(),
  });
}

function renderSpeed() {
  elements.speedValue.textContent = String(state.speedLimit);
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
    if (activePointers.size === 0) {
      releaseDirection(key);
    }
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

attachDriveButton(elements.turnLeftButton, "left");
attachDriveButton(elements.turnRightButton, "right");
attachDriveButton(elements.forwardButton, "forward");
attachDriveButton(elements.backwardButton, "backward");

window.addEventListener("blur", () => {
  state.activeButtons.clear();
  markButtonActive();
  syncDriveHoldTimer();
  void sendCurrentDriveState();
});

elements.stopButton.addEventListener("click", async () => {
  state.activeButtons.clear();
  markButtonActive();
  syncDriveHoldTimer();
  elements.motionBadge.textContent = "Holat: stop";
  await postJson("/api/control/stop", { seq: nextCommandSeq() });
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

function setBadge(element, isOnline, onlineText, offlineText) {
  element.classList.toggle("online", isOnline);
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
  ["left", "front", "right"].forEach((name) => {
    const stream =
      name === "left"
        ? elements.leftCameraStream
        : name === "front"
          ? elements.frontCameraStream
          : elements.rightCameraStream;
    if (state.availableCameras.has(name)) {
      if (!stream.src) {
        stream.src = stream.dataset.stream;
      }
    } else {
      setCameraDisabled(name);
    }
  });
}

function cameraMeta(camera, fallback) {
  if (!camera) {
    return fallback;
  }
  if (!camera.online) {
    return camera.error || "Offline";
  }
  if (camera.last_detection) {
    const detection = camera.last_detection;
    return `FPS ${camera.fps} | det ${camera.detections} | offset ${detection.offset_px}px`;
  }
  return `FPS ${camera.fps} | det ${camera.detections}`;
}

function listToHtml(items) {
  return items.map((item) => `<li>${item}</li>`).join("");
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
    const measurements = snapshot.measurements;
    const esp32 = snapshot.esp32;
    const control = snapshot.control;
    const spray = snapshot.spray;

    setBadge(
      elements.esp32Badge,
      esp32.online,
      `ESP32: online | ${esp32.firmware_mode}`,
      `ESP32: offline | ${esp32.last_error || "javob yo'q"}`
    );
    elements.marginBadge.textContent = `Yo'lak zaxirasi: ${measurements.lane_margin_cm} sm`;

    if (state.availableCameras.has("left")) {
      setBadge(elements.leftCameraBadge, snapshot.cameras.left?.online, "online", "offline");
      elements.leftCameraMeta.textContent = cameraMeta(snapshot.cameras.left, "Chap kamera");
    }
    if (state.availableCameras.has("front")) {
      setBadge(elements.frontCameraBadge, snapshot.cameras.front?.online, "online", "offline");
      elements.frontCameraMeta.textContent = cameraMeta(snapshot.cameras.front, "Old kamera");
    }
    if (state.availableCameras.has("right")) {
      setBadge(elements.rightCameraBadge, snapshot.cameras.right?.online, "online", "offline");
      elements.rightCameraMeta.textContent = cameraMeta(snapshot.cameras.right, "O'ng kamera");
    }

    elements.warningsList.innerHTML = listToHtml(
      snapshot.warnings.length ? snapshot.warnings : ["Ogohlantirish yo'q"]
    );

    elements.diagEsp32.innerHTML = `
      <p>Base URL: ${esp32.base_url}</p>
      <p>Firmware: ${esp32.firmware_mode}</p>
      <p>Auto spray: ${control.auto_spray ? "yoqilgan" : "o'chirilgan"}</p>
      <p>Oxirgi spray: ${spray.last_pump || "-"} | ${spray.last_camera || "-"} | ${spray.last_trigger_at || "-"}</p>
    `;

    elements.autoSprayToggle.checked = Boolean(control.auto_spray);
    state.speedLimit = Number(control.speed_limit || state.speedLimit);
    elements.speedSlider.value = String(state.speedLimit);
    renderSpeed();
  } catch (error) {
    elements.esp32Badge.textContent = `Serverga ulanib bo'lmadi: ${error}`;
  }
}

renderSpeed();
loadConfig().finally(refreshState);
setInterval(refreshState, 1000);
