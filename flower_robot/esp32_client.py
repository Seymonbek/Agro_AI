from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from flower_robot.config import Esp32Config, SUPPORTED_PUMP_ZONES
from flower_robot.serial_ports import resolve_serial_port
from flower_robot.state import RobotStateStore


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class ESP32Client:
    def __init__(
        self,
        config: Esp32Config,
        state: RobotStateStore,
        pump_zones: tuple[str, ...] | list[str] | None = None,
        serial_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._lock = threading.Lock()
        self._serial_lock = threading.Lock()
        self._serial_factory = serial_factory
        self._serial: Any | None = None
        self._last_signature: tuple[Any, ...] | None = None
        self._last_sent_at = 0.0
        zones = list(pump_zones or SUPPORTED_PUMP_ZONES)
        self._pump_zones = tuple(zone for zone in zones if zone in SUPPORTED_PUMP_ZONES)

    @property
    def _transport(self) -> str:
        return self._config.transport.strip().lower()

    def _mark_online(self) -> None:
        self._state.update_esp32(
            online=True,
            last_error=None,
            last_ok_at=time.strftime("%H:%M:%S"),
        )

    def _mark_offline(self, exc: Exception) -> None:
        self._state.update_esp32(online=False, last_error=str(exc))
        if self._transport == "serial":
            self._close_serial()

    def _http_request(self, path: str, params: dict[str, Any] | None = None) -> str:
        query = ""
        if params:
            query = "?" + urlencode(params)
        url = f"{self._config.base_url.rstrip('/')}{path}{query}"
        with urlopen(url, timeout=self._config.timeout_sec) as response:
            body = response.read(1024).decode("utf-8", errors="ignore")
        self._mark_online()
        return body

    def _make_serial(self) -> Any:
        port = resolve_serial_port(self._config.serial_port)
        if port is None and self._serial_factory is not None:
            port = self._config.serial_port
        if port is None:
            raise RuntimeError(
                "ESP32 serial port topilmadi. USB kabelni ulang yoki "
                "config.json ichida esp32.serial_port ni aniq belgilang."
            )

        if self._serial_factory is not None:
            return self._serial_factory(
                port=port,
                baudrate=self._config.baudrate,
                timeout=self._config.serial_timeout_sec,
                write_timeout=self._config.serial_timeout_sec,
            )

        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial o'rnatilmagan. `pip install pyserial` qiling.") from exc

        return serial.Serial(
            port=port,
            baudrate=self._config.baudrate,
            timeout=self._config.serial_timeout_sec,
            write_timeout=self._config.serial_timeout_sec,
        )

    def _ensure_serial(self) -> Any:
        if self._serial is not None:
            is_open = getattr(self._serial, "is_open", True)
            if is_open:
                return self._serial

        self._serial = self._make_serial()
        port_name = getattr(self._serial, "port", None) or getattr(self._serial, "name", None)
        if port_name:
            self._state.update_esp32(serial_port=str(port_name))
        if self._config.serial_ready_delay_sec > 0:
            time.sleep(self._config.serial_ready_delay_sec)
        for method_name in ("reset_input_buffer", "reset_output_buffer"):
            method = getattr(self._serial, method_name, None)
            if callable(method):
                method()
        return self._serial

    def _close_serial(self) -> None:
        with self._serial_lock:
            if self._serial is None:
                return
            close = getattr(self._serial, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            self._serial = None

    def _serial_request(self, command: str) -> str:
        with self._serial_lock:
            port = self._ensure_serial()
            line = f"{command.strip()}\n".encode("utf-8")
            port.write(line)
            flush = getattr(port, "flush", None)
            if callable(flush):
                flush()

            attempts = 8
            for _ in range(attempts):
                raw = port.readline()
                if not raw:
                    continue
                response = raw.decode("utf-8", errors="ignore").strip()
                if not response:
                    continue
                if response.startswith(("OK", "ERR", "{")):
                    if response.startswith("ERR"):
                        raise OSError(response)
                    self._mark_online()
                    return response

            raise TimeoutError(f"ESP32 serial javob bermadi: {command}")

    def _parse_status(self, body: str) -> None:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        pumps = payload.get("pumps")
        if isinstance(pumps, dict):
            self._state.update_pumps(
                **{
                    zone: bool(pumps.get(zone, False))
                    for zone in self._pump_zones
                }
            )

    def poll_status(self) -> None:
        try:
            if self._transport == "serial":
                body = self._serial_request("STATUS")
                self._parse_status(body)
                return

            path = "/api/status" if self._config.firmware_mode == "advanced" else "/"
            body = self._http_request(path)
            if self._config.firmware_mode == "advanced":
                self._parse_status(body)
        except Exception as exc:  # noqa: BLE001 - network/serial calls fail for many reasons.
            self._mark_offline(exc)

    def set_speed_limit(self, speed_limit: int) -> None:
        speed_limit = int(_clamp(speed_limit, 0, 255))
        if self._config.firmware_mode != "advanced":
            return
        try:
            if self._transport == "serial":
                self._serial_request(f"SPEED {speed_limit}")
            else:
                self._http_request("/api/speed", {"value": speed_limit})
        except Exception as exc:  # noqa: BLE001
            self._mark_offline(exc)

    def drive_tank(self, left: float, right: float, speed_limit: int) -> str:
        left = _clamp(left, -1.0, 1.0)
        right = _clamp(right, -1.0, 1.0)
        speed_limit = int(_clamp(speed_limit, 0, 255))
        signature = (round(left, 2), round(right, 2), speed_limit)

        with self._lock:
            if signature == self._last_signature and (time.monotonic() - self._last_sent_at) < 0.08:
                return "cached"

            try:
                if self._transport == "serial":
                    self._serial_request(f"DRIVE {left:.3f} {right:.3f} {speed_limit}")
                    mode = "serial"
                elif self._config.firmware_mode == "advanced":
                    self._http_request(
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
                    self._http_request(self._legacy_path(command))
                    mode = f"legacy:{command}"

                self._last_signature = signature
                self._last_sent_at = time.monotonic()
                return mode
            except (URLError, TimeoutError, OSError, RuntimeError) as exc:
                self._mark_offline(exc)
                return "offline"

    def stop(self) -> None:
        try:
            if self._transport == "serial":
                self._serial_request("STOP")
            elif self._config.firmware_mode == "advanced":
                self._http_request("/api/stop")
            else:
                self._http_request(self._legacy_path("stop"))
            self._last_signature = (0.0, 0.0, 0)
            self._last_sent_at = time.monotonic()
            self._state.update_pumps(**{zone: False for zone in self._pump_zones})
        except (URLError, TimeoutError, OSError, RuntimeError) as exc:
            self._mark_offline(exc)

    def set_pump(self, side: str, enabled: bool) -> None:
        if side not in self._pump_zones:
            return

        try:
            if self._transport == "serial":
                self._serial_request(f"PUMP {side} {'on' if enabled else 'off'}")
            elif self._config.firmware_mode == "advanced":
                self._http_request("/api/pump", {"side": side, "state": "on" if enabled else "off"})
            self._state.update_pumps(**{side: enabled})
        except Exception as exc:  # noqa: BLE001
            self._mark_offline(exc)

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
