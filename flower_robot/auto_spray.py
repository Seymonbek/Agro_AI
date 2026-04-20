from __future__ import annotations

import threading
import time

from flower_robot.config import AutoSprayConfig
from flower_robot.esp32_client import ESP32Client
from flower_robot.state import RobotStateStore
from flower_robot.vision import DetectionResult


class AutoSprayController:
    def __init__(
        self,
        config: AutoSprayConfig,
        esp32: ESP32Client,
        state: RobotStateStore,
    ) -> None:
        self._config = config
        self._esp32 = esp32
        self._state = state
        self._lock = threading.Lock()
        self._cooldown_until: dict[str, float] = {}

    def maybe_trigger(self, camera_name: str, detection: DetectionResult) -> None:
        if not self._state.snapshot()["control"]["auto_spray"]:
            return

        pump = self._config.camera_to_pump.get(camera_name)
        if pump is None:
            return

        if detection.centered_detection is None:
            return

        if self._state.snapshot()["pumps"].get(pump):
            return

        now = time.monotonic()
        with self._lock:
            if now < self._cooldown_until.get(pump, 0.0):
                return
            self._cooldown_until[pump] = now + (self._config.cooldown_ms / 1000.0)

        worker = threading.Thread(
            target=self._pulse_pump,
            args=(camera_name, pump),
            daemon=True,
        )
        worker.start()

    def _pulse_pump(self, camera_name: str, pump: str) -> None:
        self._esp32.set_pump(pump, True)
        current_state = self._state.snapshot()["spray"]
        self._state.update_spray(
            last_camera=camera_name,
            last_pump=pump,
            last_trigger_at=time.strftime("%H:%M:%S"),
            trigger_count=int(current_state["trigger_count"]) + 1,
        )
        time.sleep(self._config.pulse_ms / 1000.0)
        self._esp32.set_pump(pump, False)
