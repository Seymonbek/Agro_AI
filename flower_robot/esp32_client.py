from __future__ import annotations

import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from flower_robot.config import Esp32Config
from flower_robot.state import RobotStateStore


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class ESP32Client:
    def __init__(self, config: Esp32Config, state: RobotStateStore) -> None:
        self._config = config
        self._state = state
        self._lock = threading.Lock()
        self._last_signature: tuple[Any, ...] | None = None
        self._last_sent_at = 0.0

    def _request(self, path: str, params: dict[str, Any] | None = None) -> str:
        query = ""
        if params:
            query = "?" + urlencode(params)
        url = f"{self._config.base_url.rstrip('/')}{path}{query}"
        with urlopen(url, timeout=self._config.timeout_sec) as response:
            body = response.read(1024).decode("utf-8", errors="ignore")
        self._state.update_esp32(
            online=True,
            last_error=None,
            last_ok_at=time.strftime("%H:%M:%S"),
        )
        return body

    def poll_status(self) -> None:
        try:
            path = "/api/status" if self._config.firmware_mode == "advanced" else "/"
            self._request(path)
        except Exception as exc:  # noqa: BLE001 - network calls fail for many reasons.
            self._state.update_esp32(online=False, last_error=str(exc))

    def set_speed_limit(self, speed_limit: int) -> None:
        speed_limit = int(_clamp(speed_limit, 0, 255))
        if self._config.firmware_mode != "advanced":
            return
        try:
            self._request("/api/speed", {"value": speed_limit})
        except Exception as exc:  # noqa: BLE001
            self._state.update_esp32(online=False, last_error=str(exc))

    def drive_tank(self, left: float, right: float, speed_limit: int) -> str:
        left = _clamp(left, -1.0, 1.0)
        right = _clamp(right, -1.0, 1.0)
        speed_limit = int(_clamp(speed_limit, 0, 255))
        signature = (round(left, 2), round(right, 2), speed_limit)

        with self._lock:
            if signature == self._last_signature and (time.monotonic() - self._last_sent_at) < 0.08:
                return "cached"

            try:
                if self._config.firmware_mode == "advanced":
                    self._request(
                        "/api/drive",
                        {
                            "left": f"{left:.3f}",
                            "right": f"{right:.3f}",
                            "speed": speed_limit,
                        },
                    )
                    mode = "advanced"
                else:
                    command = self._legacy_command(left, right)
                    self._request(self._legacy_path(command))
                    mode = f"legacy:{command}"

                self._last_signature = signature
                self._last_sent_at = time.monotonic()
                return mode
            except (URLError, TimeoutError, OSError) as exc:
                self._state.update_esp32(online=False, last_error=str(exc))
                return "offline"

    def stop(self) -> None:
        try:
            if self._config.firmware_mode == "advanced":
                self._request("/api/stop")
            else:
                self._request(self._legacy_path("stop"))
            self._last_signature = (0.0, 0.0, 0)
            self._last_sent_at = time.monotonic()
        except (URLError, TimeoutError, OSError) as exc:
            self._state.update_esp32(online=False, last_error=str(exc))

    def set_pump(self, side: str, enabled: bool) -> None:
        if side not in {"left", "right"}:
            return

        try:
            if self._config.firmware_mode == "advanced":
                self._request("/api/pump", {"side": side, "state": "on" if enabled else "off"})
            self._state.update_pumps(**{side: enabled})
        except Exception as exc:  # noqa: BLE001
            self._state.update_esp32(online=False, last_error=str(exc))

    @staticmethod
    def _legacy_path(command: str) -> str:
        mapping = {
            "forward": "/F",
            "backward": "/B",
            "left": "/L",
            "right": "/R",
            "stop": "/S",
        }
        return mapping[command]

    @staticmethod
    def _legacy_command(left: float, right: float) -> str:
        threshold = 0.18
        if abs(left) < threshold and abs(right) < threshold:
            return "stop"
        if left > threshold and right > threshold:
            return "forward"
        if left < -threshold and right < -threshold:
            return "backward"
        if left > threshold and right < -threshold:
            return "left"
        if left < -threshold and right > threshold:
            return "right"
        if left > right:
            return "left"
        if right > left:
            return "right"
        return "stop"
