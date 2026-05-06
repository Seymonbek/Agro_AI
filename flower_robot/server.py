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
COMMAND_TTL_MS = 1200
MAX_COMMAND_TTL_MS = 5000
MAX_FUTURE_COMMAND_SKEW_MS = 2000
MANUAL_SPRAY_HOLD_TIMEOUT_SEC = 1.4
MANUAL_SPRAY_OWNER = "manual_spray"
SPRAY_LATCH_OWNER = "spray_latch"


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
            if path == "/api/control/spray":
                response = self.context.handle_manual_spray(payload)
                self._send_json(HTTPStatus.OK, response)
                return
            if path == "/api/control/spray-latch":
                response = self.context.handle_spray_latch(payload)
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
                response = self.context.stop_plan(payload)
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
        self._pump_claim_lock = threading.Lock()
        self._pump_claims: dict[str, set[str]] = {pump: set() for pump in self._pump_zones}
        self._pump_output_state: dict[str, bool] = {pump: False for pump in self._pump_zones}
        self._pump_test_owners: dict[str, str] = {}
        self._pump_owner_seq = 0
        self.auto_spray = AutoSprayController(
            settings.auto_spray,
            self.esp32,
            self.state,
            acquire_pumps=self._acquire_pump_claims,
            release_pumps=self._release_pump_claims,
        )
        self.vision = VisionHub(settings, self.state, detection_callback=self._handle_detection)
        self.autonomy = MissionController(self.esp32, self.state)
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._manual_seq_lock = threading.Lock()
        self._latest_manual_seq = -1
        self._turn_manual_lock_until = 0.0
        self._manual_spray_lock = threading.Lock()
        self._manual_spray_active = False
        self._manual_spray_pumps: tuple[str, ...] = ()
        self._manual_spray_last_seen = 0.0
        self._spray_latch_lock = threading.Lock()
        self._spray_latch_active = False
        self._spray_latch_pumps: tuple[str, ...] = ()

    def start_background_tasks(self) -> None:
        self.vision.start()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_background_tasks(self) -> None:
        self._monitor_stop.set()
        self.autonomy.stop("application stopped")
        self.vision.stop()

    def _monitor_loop(self) -> None:
        next_status_poll = 0.0
        while not self._monitor_stop.is_set():
            now = time.monotonic()
            self._expire_manual_spray_if_needed(now)
            if now >= next_status_poll:
                # Manual drive paytida status polling serial yo'lini band qilib qo'ymasligi kerak.
                if not self.esp32.recently_sent_command(0.35):
                    self.esp32.poll_status()
                self.state.set_notes(self._build_notes())
                next_status_poll = now + 2.0
            self._monitor_stop.wait(0.1)

    def public_config(self) -> dict[str, Any]:
        return {
            "server": {"host": self.settings.server.host, "port": self.settings.server.port},
            "server_time_ms": int(time.time() * 1000),
            "command_ttl_ms": COMMAND_TTL_MS,
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
                "turn_90_left_trim": self.settings.maneuvers.turn_90_left_trim,
                "turn_90_right_trim": self.settings.maneuvers.turn_90_right_trim,
                "turn_90_ramp_compensation_sec": self.settings.maneuvers.turn_90_ramp_compensation_sec,
                "manual_turn_min_speed_limit": self.settings.maneuvers.manual_turn_min_speed_limit,
                "manual_turn_deadband": self.settings.maneuvers.manual_turn_deadband,
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
            if seq <= self._latest_manual_seq:
                return False, seq
            self._latest_manual_seq = seq
        return True, seq

    def _ignore_stale_realtime_command(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        expired = self._expired_command_response(payload)
        if expired:
            return expired

        accepted, seq = self._accept_manual_seq(payload)
        if not accepted:
            return {"ok": True, "ignored": "stale_seq", "seq": seq}
        return None

    def _expired_command_response(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        has_expiry = "expires_at_ms" in payload
        has_sent_at = "client_sent_at_ms" in payload
        if not has_expiry and not has_sent_at:
            return None

        now_ms = int(time.time() * 1000)
        ttl_ms = int(
            _clamp(
                self._int_payload(payload, "ttl_ms", COMMAND_TTL_MS),
                100,
                MAX_COMMAND_TTL_MS,
            )
        )

        sent_at_ms: float | None = None
        if has_sent_at:
            sent_at_ms = self._float_payload(payload, "client_sent_at_ms", now_ms)
            if sent_at_ms > now_ms + MAX_FUTURE_COMMAND_SKEW_MS:
                return {
                    "ok": True,
                    "ignored": "future_command",
                    "seq": payload.get("seq"),
                }

        if has_expiry:
            expires_at_ms = self._float_payload(payload, "expires_at_ms", now_ms)
            if sent_at_ms is not None:
                expires_at_ms = min(expires_at_ms, sent_at_ms + ttl_ms)
        elif sent_at_ms is not None:
            expires_at_ms = sent_at_ms + ttl_ms
        else:
            expires_at_ms = now_ms + ttl_ms

        if now_ms > expires_at_ms:
            response: dict[str, Any] = {
                "ok": True,
                "ignored": "expired_command",
                "seq": payload.get("seq"),
                "expired_by_ms": int(now_ms - expires_at_ms),
            }
            if sent_at_ms is not None:
                response["age_ms"] = int(now_ms - sent_at_ms)
            return response
        return None

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
        ignored = self._ignore_stale_realtime_command(payload)
        if ignored:
            return ignored

        left = _clamp(self._float_payload(payload, "left", 0.0), -1.0, 1.0)
        right = _clamp(self._float_payload(payload, "right", 0.0), -1.0, 1.0)
        requested_speed_limit = int(
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
        effective_speed_limit = self._effective_manual_speed_limit(
            left,
            right,
            requested_speed_limit,
        )

        if self.state.snapshot()["autonomy"]["running"]:
            if self._turn_manual_locked():
                return {
                    "ok": True,
                    "ignored": "turn90_running",
                    "speed_limit": requested_speed_limit,
                    "effective_speed_limit": effective_speed_limit,
                }
            self.autonomy.stop("manual override")

        mode = self.esp32.drive_tank(left, right, effective_speed_limit)
        self.state.update_control(
            mode="manual",
            left=round(left, 3),
            right=round(right, 3),
            speed_limit=requested_speed_limit,
            last_command=mode,
        )
        return {
            "ok": True,
            "applied": mode,
            "speed_limit": requested_speed_limit,
            "effective_speed_limit": effective_speed_limit,
        }

    def handle_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        ignored = self._ignore_stale_realtime_command(payload or {})
        if ignored:
            return ignored

        self.autonomy.stop("manual stop")
        self._turn_manual_lock_until = 0.0
        self._clear_manual_spray_state()
        self._clear_spray_latch_state()
        self.esp32.stop()
        self.state.update_control(left=0.0, right=0.0, last_command="stop", mode="manual")
        return {"ok": True}

    def handle_speed(self, payload: dict[str, Any]) -> dict[str, Any]:
        ignored = self._ignore_stale_realtime_command(payload)
        if ignored:
            return ignored

        speed_limit = int(
            _clamp(self._int_payload(payload, "speed_limit", payload.get("value", 120)), 0, 255)
        )
        self.state.update_control(speed_limit=speed_limit)
        self.esp32.set_speed_limit(speed_limit)
        return {"ok": True, "speed_limit": speed_limit}

    def handle_pump(self, payload: dict[str, Any]) -> dict[str, Any]:
        ignored = self._ignore_stale_realtime_command(payload)
        if ignored:
            return ignored

        side = str(payload.get("side", "left"))
        if side not in self._pump_zones:
            return {"ok": False, "error": "invalid_pump_side"}
        enabled = self._bool_payload(payload, "enabled", False)
        auto_off_ms = int(
            _clamp(self._int_payload(payload, "auto_off_ms", 0), 0, MAX_COMMAND_TTL_MS)
        )
        owner = self._pump_test_owners.get(side)
        if enabled:
            new_owner = self._next_pump_owner(f"pump_test:{side}")
            self._pump_test_owners[side] = new_owner
            self._acquire_pump_claims(new_owner, (side,))
            if owner and owner != new_owner:
                self._release_pump_claims(owner, (side,))
            owner = new_owner
        elif owner:
            self._pump_test_owners.pop(side, None)
            self._release_pump_claims(owner, (side,))
        if enabled and auto_off_ms > 0:
            threading.Thread(
                target=self._auto_off_pump,
                args=(owner, side, auto_off_ms),
                daemon=True,
            ).start()
        return {"ok": True, "side": side, "enabled": enabled, "auto_off_ms": auto_off_ms}

    def handle_manual_spray(self, payload: dict[str, Any]) -> dict[str, Any]:
        ignored = self._ignore_stale_realtime_command(payload)
        if ignored:
            return ignored

        if "enabled" not in payload:
            raise ValueError("enabled true/false bo'lishi kerak.")
        enabled = self._bool_payload(payload, "enabled")
        pumps = self._parse_pumps_payload(payload)

        if enabled:
            with self._manual_spray_lock:
                previous_pumps = self._manual_spray_pumps
                should_reconfigure = (not self._manual_spray_active) or previous_pumps != pumps
                should_record = should_reconfigure
                self._manual_spray_active = True
                self._manual_spray_pumps = pumps
                self._manual_spray_last_seen = time.monotonic()
            self.state.update_control(
                manual_spray=True,
                manual_spray_pumps=list(pumps),
                last_command="manual_spray_on",
            )
            if should_reconfigure and previous_pumps and previous_pumps != pumps:
                self._release_pump_claims(MANUAL_SPRAY_OWNER, previous_pumps)
            if should_reconfigure:
                self._acquire_pump_claims(MANUAL_SPRAY_OWNER, pumps)
            if should_record:
                self._record_spray_trigger("manual", pumps)
            return {"ok": True, "enabled": True, "pumps": list(pumps)}

        with self._manual_spray_lock:
            pumps_to_stop = self._manual_spray_pumps or pumps
            was_active = self._manual_spray_active
            self._manual_spray_active = False
            self._manual_spray_pumps = ()
        self.state.update_control(
            manual_spray=False,
            manual_spray_pumps=[],
            last_command="manual_spray_off",
        )
        if was_active:
            self._release_pump_claims(MANUAL_SPRAY_OWNER, pumps_to_stop)
        return {"ok": True, "enabled": False, "pumps": list(pumps_to_stop)}

    def handle_spray_latch(self, payload: dict[str, Any]) -> dict[str, Any]:
        ignored = self._ignore_stale_realtime_command(payload)
        if ignored:
            return ignored

        if "enabled" not in payload:
            raise ValueError("enabled true/false bo'lishi kerak.")
        enabled = self._bool_payload(payload, "enabled")
        pumps = self._parse_pumps_payload(payload)

        if enabled:
            with self._spray_latch_lock:
                previous_pumps = self._spray_latch_pumps
                should_reconfigure = (not self._spray_latch_active) or previous_pumps != pumps
                self._spray_latch_active = True
                self._spray_latch_pumps = pumps
            self.state.update_control(
                spray_latch=True,
                spray_latch_pumps=list(pumps),
                last_command="spray_latch_on",
            )
            if should_reconfigure and previous_pumps and previous_pumps != pumps:
                self._release_pump_claims(SPRAY_LATCH_OWNER, previous_pumps)
            if should_reconfigure:
                self._acquire_pump_claims(SPRAY_LATCH_OWNER, pumps)
                self._record_spray_trigger("latch", pumps)
            return {"ok": True, "enabled": True, "pumps": list(pumps)}

        with self._spray_latch_lock:
            pumps_to_stop = self._spray_latch_pumps or pumps
            was_active = self._spray_latch_active
            self._spray_latch_active = False
            self._spray_latch_pumps = ()
        self.state.update_control(
            spray_latch=False,
            spray_latch_pumps=[],
            last_command="spray_latch_off",
        )
        if was_active:
            self._release_pump_claims(SPRAY_LATCH_OWNER, pumps_to_stop)
        return {"ok": True, "enabled": False, "pumps": list(pumps_to_stop)}

    def handle_auto_spray(self, payload: dict[str, Any]) -> dict[str, Any]:
        ignored = self._ignore_stale_realtime_command(payload)
        if ignored:
            return ignored

        enabled = self._bool_payload(payload, "enabled", False)
        self.state.update_control(auto_spray=enabled)
        return {"ok": True, "enabled": enabled, "firmware_mode": self.settings.esp32.firmware_mode}

    def handle_turn_90(self, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        ignored = self._ignore_stale_realtime_command(payload)
        if ignored:
            return ignored, HTTPStatus.OK

        direction = str(payload.get("direction", "")).strip().lower()
        if direction not in TURN_DIRECTIONS:
            raise ValueError("direction left yoki right bo'lishi kerak.")

        plan = self._build_turn_90_plan(direction)
        self._turn_manual_lock_until = time.monotonic() + plan.total_seconds + 0.45
        self.autonomy.start(plan)
        self.state.update_control(left=0.0, right=0.0, last_command=f"turn90:{direction}")
        return {
            "ok": True,
            "direction": direction,
            "message": f"{plan.name} ishga tushdi.",
            "total_seconds": plan.total_seconds,
        }, HTTPStatus.OK

    def preview_plan(self, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        ignored = self._ignore_stale_realtime_command(payload)
        if ignored:
            return ignored, HTTPStatus.OK

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
        ignored = self._ignore_stale_realtime_command(payload)
        if ignored:
            return ignored, HTTPStatus.OK

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

    def stop_plan(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        ignored = self._ignore_stale_realtime_command(payload or {})
        if ignored:
            return ignored

        self.autonomy.stop("manual stop")
        self._turn_manual_lock_until = 0.0
        return {"ok": True}

    def _handle_detection(self, camera_name: str, detection: Any) -> None:
        self.auto_spray.maybe_trigger(camera_name, detection)

    def _parse_pumps_payload(self, payload: dict[str, Any]) -> tuple[str, ...]:
        raw_pumps = payload.get("pumps", payload.get("sides", list(self._pump_zones)))
        if isinstance(raw_pumps, str):
            candidates = [item.strip() for item in raw_pumps.split(",")]
        elif isinstance(raw_pumps, (list, tuple)):
            candidates = [str(item).strip() for item in raw_pumps]
        else:
            raise ValueError("pumps ro'yxat yoki comma-separated string bo'lishi kerak.")

        pumps: list[str] = []
        for candidate in candidates:
            pump = candidate.lower()
            if not pump:
                continue
            if pump not in self._pump_zones:
                raise ValueError(f"pump kanali noto'g'ri: {pump}")
            if pump not in pumps:
                pumps.append(pump)

        if not pumps:
            raise ValueError("Kamida bitta pump kanali kerak.")
        return tuple(pumps)

    def _auto_off_pump(self, owner: str | None, side: str, auto_off_ms: int) -> None:
        time.sleep(auto_off_ms / 1000.0)
        if owner is None:
            return
        if self._pump_test_owners.get(side) == owner:
            self._pump_test_owners.pop(side, None)
        self._release_pump_claims(owner, (side,))

    def _clear_manual_spray_state(self) -> None:
        with self._manual_spray_lock:
            pumps_to_release = self._manual_spray_pumps
            self._manual_spray_active = False
            self._manual_spray_pumps = ()
            self._manual_spray_last_seen = 0.0
        if pumps_to_release:
            self._release_pump_claims(MANUAL_SPRAY_OWNER, pumps_to_release)
        self.state.update_control(manual_spray=False, manual_spray_pumps=[])

    def _clear_spray_latch_state(self) -> None:
        with self._spray_latch_lock:
            pumps_to_release = self._spray_latch_pumps
            self._spray_latch_active = False
            self._spray_latch_pumps = ()
        if pumps_to_release:
            self._release_pump_claims(SPRAY_LATCH_OWNER, pumps_to_release)
        self.state.update_control(spray_latch=False, spray_latch_pumps=[])

    def _expire_manual_spray_if_needed(self, now: float) -> None:
        with self._manual_spray_lock:
            if not self._manual_spray_active:
                return
            if now - self._manual_spray_last_seen <= MANUAL_SPRAY_HOLD_TIMEOUT_SEC:
                return
            pumps_to_stop = self._manual_spray_pumps
            self._manual_spray_active = False
            self._manual_spray_pumps = ()
            self._manual_spray_last_seen = 0.0

        self._release_pump_claims(MANUAL_SPRAY_OWNER, pumps_to_stop)
        self.state.update_control(
            manual_spray=False,
            manual_spray_pumps=[],
            last_command="manual_spray_timeout",
        )

    def _next_pump_owner(self, prefix: str) -> str:
        with self._pump_claim_lock:
            self._pump_owner_seq += 1
            return f"{prefix}:{self._pump_owner_seq}"

    def _acquire_pump_claims(self, owner: str, pumps: tuple[str, ...]) -> None:
        self._update_pump_claims(owner, pumps, enabled=True)

    def _release_pump_claims(self, owner: str, pumps: tuple[str, ...]) -> None:
        self._update_pump_claims(owner, pumps, enabled=False)

    def _update_pump_claims(self, owner: str, pumps: tuple[str, ...], enabled: bool) -> None:
        updates: list[tuple[str, bool]] = []
        with self._pump_claim_lock:
            for pump in pumps:
                if pump not in self._pump_claims:
                    continue
                holders = self._pump_claims[pump]
                was_enabled = bool(holders)
                if enabled:
                    holders.add(owner)
                else:
                    holders.discard(owner)
                should_enable = bool(holders)
                if should_enable == was_enabled:
                    continue
                self._pump_output_state[pump] = should_enable
                updates.append((pump, should_enable))

        for pump, state in updates:
            self.esp32.set_pump(pump, state)

    def _record_spray_trigger(self, camera_name: str, pumps: tuple[str, ...]) -> None:
        current_state = self.state.snapshot()["spray"]
        zones = current_state.get("zones", {})
        triggered_at = time.strftime("%H:%M:%S")
        for pump in pumps:
            zone_state = zones.get(pump, {"trigger_count": 0, "last_trigger_at": None})
            zones[pump] = {
                "trigger_count": int(zone_state.get("trigger_count", 0)) + 1,
                "last_trigger_at": triggered_at,
            }
        self.state.update_spray(
            last_camera=camera_name,
            last_pump=pumps[0] if len(pumps) == 1 else ",".join(pumps),
            last_pumps=list(pumps),
            last_trigger_at=triggered_at,
            trigger_count=int(current_state["trigger_count"]) + 1,
            zones=zones,
        )

    def _effective_manual_speed_limit(self, left: float, right: float, speed_limit: int) -> int:
        if speed_limit <= 0:
            return 0

        turn_delta = abs(left - right)
        deadband = max(float(self.settings.maneuvers.manual_turn_deadband), 0.0)
        if turn_delta <= deadband:
            return speed_limit

        min_turn_speed = int(_clamp(int(self.settings.maneuvers.manual_turn_min_speed_limit), 0, 255))
        return max(speed_limit, min_turn_speed)

    def _turn_manual_locked(self) -> bool:
        return time.monotonic() < self._turn_manual_lock_until

    def _build_turn_90_plan(self, direction: str) -> MissionPlan:
        turn_speed = _clamp(float(self.settings.maneuvers.turn_90_speed), 0.15, 1.0)
        speed_limit = int(_clamp(int(self.settings.maneuvers.turn_90_speed_limit), 0, 255))
        ramp_compensation = max(float(self.settings.maneuvers.turn_90_ramp_compensation_sec), 0.0)
        if direction == "left":
            label = "90° chapga burilish"
            duration = max(float(self.settings.maneuvers.turn_90_left_seconds), 0.05)
            trim = _clamp(float(self.settings.maneuvers.turn_90_left_trim), 0.6, 1.8)
            left = turn_speed
            right = -turn_speed
        else:
            label = "90° o'ngga burilish"
            duration = max(float(self.settings.maneuvers.turn_90_right_seconds), 0.05)
            trim = _clamp(float(self.settings.maneuvers.turn_90_right_trim), 0.6, 1.8)
            left = -turn_speed
            right = turn_speed

        calibrated_duration = max((duration * trim) + ramp_compensation, 0.05)

        return MissionPlan(
            name=label,
            speed_limit=speed_limit,
            segments=[
                MissionSegment(
                    label=label,
                    left=left,
                    right=right,
                    duration_seconds=round(calibrated_duration, 2),
                )
            ],
            warnings=[
                "90° burilish vaqt bo'yicha kalibrovka bilan ishlaydi.",
                "Nozik sozlash uchun config.json ichida maneuvers.turn_90_left/right_seconds va *_trim ni moslang.",
            ],
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
