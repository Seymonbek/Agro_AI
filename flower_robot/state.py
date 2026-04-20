from __future__ import annotations

import copy
import threading
import time
from typing import Any

from flower_robot.config import AppSettings


class RobotStateStore:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._state: dict[str, Any] = {
            "control": {
                "mode": "manual",
                "left": 0.0,
                "right": 0.0,
                "speed_limit": 120,
                "last_command": "stop",
                "auto_spray": settings.auto_spray.default_enabled,
            },
            "esp32": {
                "online": False,
                "base_url": settings.esp32.base_url,
                "firmware_mode": settings.esp32.firmware_mode,
                "last_error": None,
                "last_ok_at": None,
            },
            "pumps": {"left": False, "right": False},
            "spray": {
                "last_camera": None,
                "last_pump": None,
                "last_trigger_at": None,
                "trigger_count": 0,
            },
            "autonomy": {
                "running": False,
                "status": "idle",
                "plan_name": "",
                "current_segment": 0,
                "current_label": "",
                "progress": 0.0,
                "remaining_seconds": 0.0,
                "warnings": [],
            },
            "plans": {"draft": None},
            "cameras": {
                camera.name: {
                    "online": False,
                    "source": camera.source,
                    "detect_flowers": camera.detect_flowers,
                    "fps": 0.0,
                    "detections": 0,
                    "last_detection": None,
                    "error": None,
                }
                for camera in settings.cameras
                if camera.enabled
            },
            "notes": [],
        }

    def update_control(self, **values: Any) -> None:
        with self._lock:
            self._state["control"].update(values)

    def update_camera(self, camera_name: str, **values: Any) -> None:
        with self._lock:
            if camera_name in self._state["cameras"]:
                self._state["cameras"][camera_name].update(values)

    def update_esp32(self, **values: Any) -> None:
        with self._lock:
            self._state["esp32"].update(values)

    def update_pumps(self, **values: Any) -> None:
        with self._lock:
            self._state["pumps"].update(values)

    def update_spray(self, **values: Any) -> None:
        with self._lock:
            self._state["spray"].update(values)

    def update_autonomy(self, **values: Any) -> None:
        with self._lock:
            self._state["autonomy"].update(values)

    def set_draft_plan(self, draft: dict[str, Any] | None) -> None:
        with self._lock:
            self._state["plans"]["draft"] = draft

    def set_notes(self, notes: list[str]) -> None:
        with self._lock:
            self._state["notes"] = notes

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snap = copy.deepcopy(self._state)

        measurements = self._settings.measurements
        snap["uptime_sec"] = round(time.monotonic() - self._started_at, 1)
        snap["measurements"] = {
            "lane_width_cm": measurements.lane_width_cm,
            "robot_width_cm": measurements.robot_width_cm,
            "row_length_m": measurements.row_length_m,
            "full_speed_mps": measurements.full_speed_mps,
            "lane_margin_cm": measurements.lane_margin_cm,
        }
        snap["warnings"] = self._build_warnings(snap)
        return snap

    def _build_warnings(self, snap: dict[str, Any]) -> list[str]:
        margin = self._settings.measurements.lane_margin_cm
        warnings: list[str] = []
        if margin <= 2.5:
            warnings.append(
                "Qator oralig'i juda tor: har tomonda taxminan 2-2.5 smgina zaxira bor."
            )
        elif margin <= 5:
            warnings.append(
                "Avtonom yurish uchun yon sensor bilan markazda ushlash tavsiya qilinadi."
            )

        if self._settings.esp32.firmware_mode == "legacy":
            warnings.append(
                "ESP32 legacy rejimida: dinamik chap/o'ng PWM uchun advanced firmware tavsiya qilinadi."
            )

        if snap["autonomy"]["running"]:
            warnings.extend(snap["autonomy"].get("warnings", []))
        return warnings
