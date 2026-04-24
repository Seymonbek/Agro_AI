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

        pumps = list(self._config.camera_to_pump.get(camera_name, ()))
        if not pumps:
            return

        if detection.centered_detection is None:
            return

        pump_state = self._state.snapshot()["pumps"]
        if any(pump_state.get(pump) for pump in pumps):
            return

        now = time.monotonic()
        with self._lock:
            if any(now < self._cooldown_until.get(pump, 0.0) for pump in pumps):
                return
            cooldown_until = now + (self._config.cooldown_ms / 1000.0)
            for pump in pumps:
                self._cooldown_until[pump] = cooldown_until

        worker = threading.Thread(
            target=self._pulse_pumps,
            args=(camera_name, tuple(pumps)),
            daemon=True,
        )
        worker.start()

    def _pulse_pumps(self, camera_name: str, pumps: tuple[str, ...]) -> None:
        for pump in pumps:
            self._esp32.set_pump(pump, True)
        current_state = self._state.snapshot()["spray"]
        zones = current_state.get("zones", {})
        triggered_at = time.strftime("%H:%M:%S")
        for pump in pumps:
            zone_state = zones.get(pump, {"trigger_count": 0, "last_trigger_at": None})
            zones[pump] = {
                "trigger_count": int(zone_state.get("trigger_count", 0)) + 1,
                "last_trigger_at": triggered_at,
            }
        self._state.update_spray(
            last_camera=camera_name,
            last_pump=pumps[0] if len(pumps) == 1 else ",".join(pumps),
            last_pumps=list(pumps),
            last_trigger_at=triggered_at,
            trigger_count=int(current_state["trigger_count"]) + 1,
            zones=zones,
        )
        time.sleep(self._config.pulse_ms / 1000.0)
        for pump in pumps:
            self._esp32.set_pump(pump, False)
