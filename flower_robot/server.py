from __future__ import annotations

import errno
import json
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from flower_robot.auto_spray import AutoSprayController
from flower_robot.autonomy import MissionController, MissionPlan, MissionSegment, build_mission_plan
from flower_robot.config import AppSettings
from flower_robot.esp32_client import ESP32Client
from flower_robot.paths import resource_path
from flower_robot.state import RobotStateStore
from flower_robot.vision import VisionHub


STATIC_ROOT = resource_path("flower_robot", "static")
TURN_DIRECTIONS = {"left", "right"}


class RequestJsonError(ValueError):
    pass


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "FlowerRobotHTTP/0.1"

    def __init__(self, *args: Any, context: "AppContext", **kwargs: Any) -> None:
        self.context = context
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path in {"/manual", "/autonomy", "/diagnostics"}:
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if path == "/assets/style.css":
            self._serve_static("style.css", "text/css; charset=utf-8")
            return
        if path == "/assets/app.js":
            self._serve_static("app.js", "application/javascript; charset=utf-8")
            return
        if path == "/manifest.webmanifest":
            self._serve_static("manifest.webmanifest", "application/manifest+json; charset=utf-8")
            return
        if path == "/service-worker.js":
            self._serve_static("service-worker.js", "application/javascript; charset=utf-8")
            return
        if path.startswith("/assets/icons/"):
            self._serve_static(path.removeprefix("/assets/"), "image/png")
            return
        if path == "/api/state":
            self._send_json(HTTPStatus.OK, self.context.state.snapshot())
            return
        if path == "/api/config":
            self._send_json(HTTPStatus.OK, self.context.public_config())
            return
        if path.startswith("/stream/"):
            camera_name = path.split("/")[-1]
            self._serve_stream(camera_name)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint topilmadi."})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self._read_json()
        except RequestJsonError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "bad_json", "detail": str(exc)},
            )
            return

        try:
            if path == "/api/control/tank":
                response = self.context.handle_tank_command(payload)
                self._send_json(HTTPStatus.OK, response)
                return
            if path == "/api/control/stop":
                response = self.context.handle_stop(payload)
                self._send_json(HTTPStatus.OK, response)
                return
            if path == "/api/control/speed":
                response = self.context.handle_speed(payload)
                self._send_json(HTTPStatus.OK, response)
                return
            if path == "/api/control/pump":
                response = self.context.handle_pump(payload)
                self._send_json(HTTPStatus.OK, response)
                return
            if path == "/api/control/auto-spray":
                response = self.context.handle_auto_spray(payload)
                self._send_json(HTTPStatus.OK, response)
                return
            if path == "/api/control/turn90":
                response, code = self.context.handle_turn_90(payload)
                self._send_json(code, response)
                return
            if path == "/api/autonomy/plan":
                response, code = self.context.preview_plan(payload)
                self._send_json(code, response)
                return
            if path == "/api/autonomy/start":
                response, code = self.context.start_plan(payload)
                self._send_json(code, response)
                return
            if path == "/api/autonomy/stop":
                response = self.context.stop_plan()
                self._send_json(HTTPStatus.OK, response)
                return
        except ValueError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "bad_request", "detail": str(exc)},
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "POST endpoint topilmadi."})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise RequestJsonError("Content-Length noto'g'ri.") from exc
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestJsonError("JSON format noto'g'ri.") from exc
        if not isinstance(payload, dict):
            raise RequestJsonError("JSON object bo'lishi kerak.")
        return payload

    def _serve_static(self, file_name: str, content_type: str) -> None:
        file_path = STATIC_ROOT / file_name
        if not file_path.exists():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"{file_name} topilmadi."})
            return
        content = file_path.read_bytes()
        self._send_bytes(HTTPStatus.OK, content, content_type)

    def _serve_stream(self, camera_name: str) -> None:
        if camera_name not in self.context.vision.camera_names:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Kamera topilmadi."})
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        try:
            while True:
                frame = self.context.vision.get_jpeg(camera_name)
                if frame is None:
                    time.sleep(0.1)
                    continue
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                time.sleep(0.07)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        content = _json_bytes(payload)
        self._send_bytes(status, content, "application/json; charset=utf-8")

    def _send_bytes(self, status: HTTPStatus, content: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            return


class AppContext:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.state = RobotStateStore(settings)
        self._pump_zones = tuple(settings.auto_spray.pump_zones)
        self.esp32 = ESP32Client(settings.esp32, self.state, pump_zones=self._pump_zones)
        self.auto_spray = AutoSprayController(settings.auto_spray, self.esp32, self.state)
        self.vision = VisionHub(settings, self.state, detection_callback=self._handle_detection)
        self.autonomy = MissionController(self.esp32, self.state)
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._manual_seq_lock = threading.Lock()
        self._latest_manual_seq = -1

    def start_background_tasks(self) -> None:
        self.vision.start()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_background_tasks(self) -> None:
        self._monitor_stop.set()
        self.autonomy.stop("application stopped")
        self.vision.stop()

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.is_set():
            self.esp32.poll_status()
            self.state.set_notes(self._build_notes())
            self._monitor_stop.wait(2.0)

    def public_config(self) -> dict[str, Any]:
        return {
            "server": {"host": self.settings.server.host, "port": self.settings.server.port},
            "esp32": {
                "transport": self.settings.esp32.transport,
                "base_url": self.settings.esp32.base_url,
                "serial_port": self.settings.esp32.serial_port,
                "baudrate": self.settings.esp32.baudrate,
                "firmware_mode": self.settings.esp32.firmware_mode,
            },
            "measurements": {
                "lane_width_cm": self.settings.measurements.lane_width_cm,
                "robot_width_cm": self.settings.measurements.robot_width_cm,
                "row_length_m": self.settings.measurements.row_length_m,
                "lane_margin_cm": self.settings.measurements.lane_margin_cm,
            },
            "auto_spray": {
                "default_enabled": self.settings.auto_spray.default_enabled,
                "pulse_ms": self.settings.auto_spray.pulse_ms,
                "cooldown_ms": self.settings.auto_spray.cooldown_ms,
                "center_tolerance_px": self.settings.auto_spray.center_tolerance_px,
                "camera_to_pump": self.settings.auto_spray.camera_to_pump,
                "spray_zones": list(self._pump_zones),
            },
            "maneuvers": {
                "turn_90_speed": self.settings.maneuvers.turn_90_speed,
                "turn_90_speed_limit": self.settings.maneuvers.turn_90_speed_limit,
                "turn_90_left_seconds": self.settings.maneuvers.turn_90_left_seconds,
                "turn_90_right_seconds": self.settings.maneuvers.turn_90_right_seconds,
            },
            "cameras": [
                {
                    "name": camera.name,
                    "source": camera.source,
                    "detect_flowers": camera.detect_flowers,
                }
                for camera in self.settings.cameras
                if camera.enabled
            ],
            "config_path": str(self.settings.config_path),
        }

    def _accept_manual_seq(self, payload: dict[str, Any]) -> tuple[bool, int | None]:
        raw_seq = payload.get("seq")
        if raw_seq is None:
            return True, None

        try:
            seq = int(raw_seq)
        except (TypeError, ValueError):
            return True, None

        with self._manual_seq_lock:
            if seq < self._latest_manual_seq:
                return False, seq
            self._latest_manual_seq = seq
        return True, seq

    @staticmethod
    def _float_payload(payload: dict[str, Any], key: str, default: float) -> float:
        raw_value = payload.get(key, default)
        try:
            return float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} son bo'lishi kerak.") from exc

    @staticmethod
    def _int_payload(payload: dict[str, Any], key: str, default: Any) -> int:
        raw_value = payload.get(key, default)
        try:
            return int(float(raw_value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} butun son bo'lishi kerak.") from exc

    @staticmethod
    def _bool_payload(payload: dict[str, Any], key: str, default: bool = False) -> bool:
        raw_value = payload.get(key, default)
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, (int, float)):
            return bool(raw_value)
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in {"1", "true", "on", "yes"}:
                return True
            if normalized in {"0", "false", "off", "no"}:
                return False
        raise ValueError(f"{key} true/false bo'lishi kerak.")

    def handle_tank_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        accepted, seq = self._accept_manual_seq(payload)
        if not accepted:
            return {"ok": True, "ignored": "stale", "seq": seq}

        left = _clamp(self._float_payload(payload, "left", 0.0), -1.0, 1.0)
        right = _clamp(self._float_payload(payload, "right", 0.0), -1.0, 1.0)
        speed_limit = int(
            _clamp(
                self._int_payload(
                    payload,
                    "speed_limit",
                    int(self.state.snapshot()["control"]["speed_limit"]),
                ),
                0,
                255,
            )
        )

        if self.state.snapshot()["autonomy"]["running"]:
            self.autonomy.stop("manual override")

        mode = self.esp32.drive_tank(left, right, speed_limit)
        self.state.update_control(
            mode="manual",
            left=round(left, 3),
            right=round(right, 3),
            speed_limit=speed_limit,
            last_command=mode,
        )
        return {"ok": True, "applied": mode}

    def handle_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        accepted, seq = self._accept_manual_seq(payload or {})
        if not accepted:
            return {"ok": True, "ignored": "stale", "seq": seq}

        self.autonomy.stop("manual stop")
        self.esp32.stop()
        self.state.update_control(left=0.0, right=0.0, last_command="stop", mode="manual")
        return {"ok": True}

    def handle_speed(self, payload: dict[str, Any]) -> dict[str, Any]:
        speed_limit = int(
            _clamp(self._int_payload(payload, "speed_limit", payload.get("value", 120)), 0, 255)
        )
        self.state.update_control(speed_limit=speed_limit)
        self.esp32.set_speed_limit(speed_limit)
        return {"ok": True, "speed_limit": speed_limit}

    def handle_pump(self, payload: dict[str, Any]) -> dict[str, Any]:
        side = str(payload.get("side", "left"))
        if side not in self._pump_zones:
            return {"ok": False, "error": "invalid_pump_side"}
        enabled = self._bool_payload(payload, "enabled", False)
        self.esp32.set_pump(side, enabled)
        return {"ok": True, "side": side, "enabled": enabled}

    def handle_auto_spray(self, payload: dict[str, Any]) -> dict[str, Any]:
        enabled = self._bool_payload(payload, "enabled", False)
        self.state.update_control(auto_spray=enabled)
        return {"ok": True, "enabled": enabled, "firmware_mode": self.settings.esp32.firmware_mode}

    def handle_turn_90(self, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        direction = str(payload.get("direction", "")).strip().lower()
        if direction not in TURN_DIRECTIONS:
            raise ValueError("direction left yoki right bo'lishi kerak.")

        plan = self._build_turn_90_plan(direction)
        self.autonomy.start(plan)
        self.state.update_control(left=0.0, right=0.0, last_command=f"turn90:{direction}")
        return {
            "ok": True,
            "direction": direction,
            "message": f"{plan.name} ishga tushdi.",
            "total_seconds": plan.total_seconds,
        }, HTTPStatus.OK

    def preview_plan(self, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        try:
            plan = build_mission_plan(payload, self.settings.measurements)
            self._validate_plan_pumps(plan)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST

        draft = {
            "name": plan.name,
            "speed_limit": plan.speed_limit,
            "segments": [
                {
                    "label": segment.label,
                    "left": segment.left,
                    "right": segment.right,
                    "seconds": segment.duration_seconds,
                    "meters": segment.distance_m,
                    "pump": segment.pump,
                }
                for segment in plan.segments
            ],
            "total_seconds": plan.total_seconds,
            "total_distance_m": plan.total_distance_m,
            "warnings": plan.warnings,
        }
        self.state.set_draft_plan(draft)
        return {"ok": True, "plan": draft}, HTTPStatus.OK

    def start_plan(self, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        source_payload = payload
        if not payload.get("segments"):
            draft = self.state.snapshot()["plans"]["draft"]
            if draft and draft.get("segments"):
                source_payload = draft

        try:
            plan = build_mission_plan(source_payload, self.settings.measurements)
            self._validate_plan_pumps(plan)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST

        self.autonomy.start(plan)
        return {
            "ok": True,
            "message": f"{plan.name} ishga tushdi.",
            "total_seconds": plan.total_seconds,
        }, HTTPStatus.OK

    def stop_plan(self) -> dict[str, Any]:
        self.autonomy.stop("manual stop")
        return {"ok": True}

    def _handle_detection(self, camera_name: str, detection: Any) -> None:
        self.auto_spray.maybe_trigger(camera_name, detection)

    def _build_turn_90_plan(self, direction: str) -> MissionPlan:
        turn_speed = _clamp(float(self.settings.maneuvers.turn_90_speed), 0.15, 1.0)
        speed_limit = int(_clamp(int(self.settings.maneuvers.turn_90_speed_limit), 0, 255))
        if direction == "left":
            label = "90° chapga burilish"
            duration = max(float(self.settings.maneuvers.turn_90_left_seconds), 0.05)
            left = turn_speed
            right = -turn_speed
        else:
            label = "90° o'ngga burilish"
            duration = max(float(self.settings.maneuvers.turn_90_right_seconds), 0.05)
            left = -turn_speed
            right = turn_speed

        return MissionPlan(
            name=label,
            speed_limit=speed_limit,
            segments=[
                MissionSegment(
                    label=label,
                    left=left,
                    right=right,
                    duration_seconds=round(duration, 2),
                )
            ],
            warnings=["90° burilish vaqt bo'yicha kalibrovka bilan ishlaydi."],
        )

    def _validate_plan_pumps(self, plan: MissionPlan) -> None:
        invalid_pumps = sorted(
            {
                segment.pump
                for segment in plan.segments
                if segment.pump and segment.pump not in self._pump_zones
            }
        )
        if invalid_pumps:
            raise ValueError(
                "Rejada ishlatib bo'lmaydigan pump kanali bor: " + ", ".join(invalid_pumps)
            )

    def _build_notes(self) -> list[str]:
        notes = [
            "Chel ustidan yurish konfiguratsiyasi real hardware geometriyasiga moslanadi.",
            "Aniq avtonom yurish uchun encoder, IMU yoki vision feedback qo'shish mumkin.",
            "Laptopdagi local server telefon brauzeridan ochiladi, cloud server shart emas.",
        ]
        if self.settings.esp32.firmware_mode == "advanced":
            notes.append("Auto spray yoqilsa detect qiluvchi kamera markazga tushgan gul uchun configdagi spray kanal(lar)iga pulse yuboriladi.")
        if self.settings.esp32.transport == "serial":
            notes.append(f"ESP32 USB serial orqali ulanadi: {self.settings.esp32.serial_port}.")
        return notes


class RobotApplication:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._context = AppContext(settings)
        self._httpd: ThreadingHTTPServer | None = None

    def serve_forever(self) -> None:
        handler = partial(RequestHandler, context=self._context)
        address = f"http://{self._settings.server.host}:{self._settings.server.port}"

        try:
            self._httpd = ThreadingHTTPServer(
                (self._settings.server.host, self._settings.server.port),
                handler,
            )
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                print(f"Port band: {address}")
                print("Boshqa serverni to'xtating yoki --port bilan boshqa port tanlang.")
                raise SystemExit(1) from exc
            raise

        self._context.start_background_tasks()
        print(f"Flower Rover Control Center ishga tushdi: {address}")
        print("Telefonni shu tarmoqda ulab brauzerdan shu manzilni oching.")
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer to'xtatildi.")
        finally:
            if self._httpd:
                self._httpd.server_close()
            self._context.stop_background_tasks()
