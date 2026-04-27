from __future__ import annotations

import json
import threading
import time
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flower_robot.config import load_settings
from flower_robot.server import AppContext, RequestHandler
from flower_robot.vision import DetectionResult


class FlowerRobotHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings()
        self.settings.server.host = "127.0.0.1"
        self.settings.cameras = []
        self.context = AppContext(self.settings)
        self.context.start_background_tasks()
        handler = partial(RequestHandler, context=self.context)
        self.httpd = ThreadingHTTPServer((self.settings.server.host, 0), handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.2)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.context.stop_background_tasks()
        self.thread.join(timeout=1.0)

    def post_json(self, path: str, payload: dict[str, object]) -> tuple[int, str]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, response.read().decode("utf-8")
        except HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    @staticmethod
    def expired_command_payload(**values: object) -> dict[str, object]:
        now_ms = int(time.time() * 1000)
        return {
            **values,
            "client_sent_at_ms": now_ms - 2500,
            "expires_at_ms": now_ms - 1000,
            "ttl_ms": 500,
        }

    def test_api_config_route(self) -> None:
        with urlopen(f"{self.base_url}/api/config", timeout=3) as response:
            body = response.read().decode("utf-8")
        self.assertIn('"esp32"', body)
        self.assertIn('"server"', body)
        self.assertIn('"front"', body)
        self.assertIn('"spray_zones"', body)

    def test_api_state_route(self) -> None:
        with urlopen(f"{self.base_url}/api/state", timeout=3) as response:
            body = response.read().decode("utf-8")
        self.assertIn('"control"', body)
        self.assertIn('"measurements"', body)

    def test_autonomy_page_route(self) -> None:
        with urlopen(f"{self.base_url}/autonomy", timeout=3) as response:
            body = response.read().decode("utf-8")
        self.assertIn("autonomyPage", body)
        self.assertIn("missionSegments", body)

    def test_manual_and_diagnostics_routes_render_app(self) -> None:
        for path in ("/manual", "/diagnostics"):
            with self.subTest(path=path):
                with urlopen(f"{self.base_url}{path}", timeout=3) as response:
                    body = response.read().decode("utf-8")
                self.assertIn("operatorPage", body)
                self.assertIn("diagnosticsPage", body)

    def test_unknown_route_returns_404(self) -> None:
        with self.assertRaises(HTTPError) as context:
            urlopen(f"{self.base_url}/nope", timeout=3)

        self.assertEqual(context.exception.code, 404)

    def test_pwa_assets(self) -> None:
        with urlopen(f"{self.base_url}/manifest.webmanifest", timeout=3) as response:
            manifest = response.read().decode("utf-8")
        self.assertIn('"display": "standalone"', manifest)

        with urlopen(f"{self.base_url}/service-worker.js", timeout=3) as response:
            service_worker = response.read().decode("utf-8")
        self.assertIn("flower-rover-shell", service_worker)

        with urlopen(f"{self.base_url}/assets/icons/flower-rover-192.png", timeout=3) as response:
            icon = response.read(8)
        self.assertEqual(icon, b"\x89PNG\r\n\x1a\n")

    def test_left_pump_api_route(self) -> None:
        calls: list[tuple[str, bool]] = []
        self.context.esp32.set_pump = lambda side, enabled: calls.append((side, enabled))  # type: ignore[method-assign]

        request = Request(
            f"{self.base_url}/api/control/pump",
            data=b'{"side":"left","enabled":true}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            body = response.read().decode("utf-8")

        self.assertIn('"ok": true', body)
        self.assertEqual(calls, [("left", True)])

    def test_pump_test_auto_off_turns_pump_off_without_second_request(self) -> None:
        calls: list[tuple[str, bool]] = []
        self.context.esp32.set_pump = lambda side, enabled: calls.append((side, enabled))  # type: ignore[method-assign]

        status, body = self.post_json(
            "/api/control/pump",
            {"side": "left", "enabled": True, "auto_off_ms": 50},
        )
        time.sleep(0.12)

        self.assertEqual(status, 200)
        self.assertIn('"auto_off_ms": 50', body)
        self.assertEqual(calls, [("left", True), ("left", False)])

    def test_pump_test_auto_off_does_not_interrupt_manual_spray(self) -> None:
        calls: list[tuple[str, bool]] = []
        self.context.esp32.set_pump = lambda side, enabled: (  # type: ignore[method-assign]
            calls.append((side, enabled)),
            self.context.state.update_pumps(**{side: enabled}),
        )

        self.context.handle_manual_spray({"enabled": True})
        status, body = self.post_json(
            "/api/control/pump",
            {"side": "left", "enabled": True, "auto_off_ms": 50},
        )
        time.sleep(0.12)

        self.assertEqual(status, 200)
        self.assertIn('"auto_off_ms": 50', body)
        self.assertEqual(calls, [("left", True), ("right", True)])
        self.assertTrue(self.context.state.snapshot()["pumps"]["left"])

        self.context.handle_manual_spray({"enabled": False})
        self.assertEqual(
            calls,
            [("left", True), ("right", True), ("left", False), ("right", False)],
        )

    def test_manual_release_waits_for_active_auto_spray_pulse(self) -> None:
        calls: list[tuple[str, bool]] = []
        self.context.esp32.set_pump = lambda side, enabled: (  # type: ignore[method-assign]
            calls.append((side, enabled)),
            self.context.state.update_pumps(**{side: enabled}),
        )
        self.context.settings.auto_spray.pulse_ms = 120
        self.context.state.update_control(auto_spray=True)

        self.context.handle_manual_spray({"enabled": True})
        self.context.auto_spray.maybe_trigger(
            "front",
            DetectionResult(
                detections=1,
                last_detection={"centered": True},
                centered_detection={"centered": True},
            ),
        )
        time.sleep(0.03)
        self.context.handle_manual_spray({"enabled": False})

        self.assertTrue(self.context.state.snapshot()["pumps"]["left"])
        self.assertTrue(self.context.state.snapshot()["pumps"]["right"])
        time.sleep(0.14)
        self.assertEqual(
            calls,
            [("left", True), ("right", True), ("left", False), ("right", False)],
        )

    def test_manual_spray_hold_sets_and_clears_configured_pumps(self) -> None:
        calls: list[tuple[str, bool]] = []
        self.context.esp32.set_pump = lambda side, enabled: calls.append((side, enabled))  # type: ignore[method-assign]

        status, body = self.post_json("/api/control/spray", {"enabled": True})

        self.assertEqual(status, 200)
        self.assertIn('"ok": true', body)
        self.assertIn('"enabled": true', body)
        self.assertIn('"left"', body)
        self.assertIn('"right"', body)
        self.assertEqual(calls, [("left", True), ("right", True)])
        control = self.context.state.snapshot()["control"]
        self.assertTrue(control["manual_spray"])
        self.assertEqual(control["manual_spray_pumps"], ["left", "right"])

        status, body = self.post_json("/api/control/spray", {"enabled": False})

        self.assertEqual(status, 200)
        self.assertIn('"enabled": false', body)
        self.assertEqual(
            calls,
            [("left", True), ("right", True), ("left", False), ("right", False)],
        )
        control = self.context.state.snapshot()["control"]
        self.assertFalse(control["manual_spray"])
        self.assertEqual(control["manual_spray_pumps"], [])
        snapshot = self.context.state.snapshot()["spray"]
        self.assertEqual(snapshot["last_camera"], "manual")
        self.assertEqual(snapshot["last_pumps"], ["left", "right"])

    def test_manual_spray_watchdog_turns_off_when_heartbeat_stops(self) -> None:
        calls: list[tuple[str, bool]] = []
        self.context.esp32.set_pump = lambda side, enabled: calls.append((side, enabled))  # type: ignore[method-assign]

        self.context.handle_manual_spray({"enabled": True})
        self.context._manual_spray_last_seen = time.monotonic() - 3.0  # type: ignore[attr-defined]
        self.context._expire_manual_spray_if_needed(time.monotonic())  # type: ignore[attr-defined]

        self.assertEqual(
            calls,
            [("left", True), ("right", True), ("left", False), ("right", False)],
        )
        control = self.context.state.snapshot()["control"]
        self.assertFalse(control["manual_spray"])
        self.assertEqual(control["last_command"], "manual_spray_timeout")

    def test_expired_tank_command_is_ignored(self) -> None:
        calls: list[tuple[float, float, int]] = []

        def fake_drive(left: float, right: float, speed_limit: int) -> str:
            calls.append((left, right, speed_limit))
            return "fake"

        self.context.esp32.drive_tank = fake_drive  # type: ignore[method-assign]

        status, body = self.post_json(
            "/api/control/tank",
            self.expired_command_payload(left=1.0, right=1.0, speed_limit=120, seq=1),
        )

        self.assertEqual(status, 200)
        self.assertIn('"ignored": "expired_command"', body)
        self.assertEqual(calls, [])

    def test_expired_manual_spray_on_is_ignored(self) -> None:
        calls: list[tuple[str, bool]] = []
        self.context.esp32.set_pump = lambda side, enabled: calls.append((side, enabled))  # type: ignore[method-assign]

        status, body = self.post_json(
            "/api/control/spray",
            self.expired_command_payload(enabled=True, seq=1),
        )

        self.assertEqual(status, 200)
        self.assertIn('"ignored": "expired_command"', body)
        self.assertEqual(calls, [])
        self.assertFalse(self.context.state.snapshot()["control"]["manual_spray"])

    def test_stale_sequence_is_ignored_across_control_commands(self) -> None:
        calls: list[tuple[str, bool]] = []
        self.context.esp32.set_speed_limit = lambda speed: None  # type: ignore[method-assign]
        self.context.esp32.set_pump = lambda side, enabled: calls.append((side, enabled))  # type: ignore[method-assign]

        status, body = self.post_json("/api/control/speed", {"speed_limit": 150, "seq": 8})
        self.assertEqual(status, 200)

        status, body = self.post_json(
            "/api/control/pump",
            {"side": "left", "enabled": True, "seq": 7},
        )

        self.assertEqual(status, 200)
        self.assertIn('"ignored": "stale_seq"', body)
        self.assertEqual(calls, [])

    def test_tank_command_clamps_values(self) -> None:
        calls: list[tuple[float, float, int]] = []

        def fake_drive(left: float, right: float, speed_limit: int) -> str:
            calls.append((left, right, speed_limit))
            return "fake"

        self.context.esp32.drive_tank = fake_drive  # type: ignore[method-assign]

        status, body = self.post_json(
            "/api/control/tank",
            {"left": 2.5, "right": -2.5, "speed_limit": 999, "seq": 1},
        )

        self.assertEqual(status, 200)
        self.assertIn('"applied": "fake"', body)
        self.assertEqual(calls, [(1.0, -1.0, 255)])

    def test_low_speed_turn_uses_minimum_turn_torque(self) -> None:
        calls: list[tuple[float, float, int]] = []

        def fake_drive(left: float, right: float, speed_limit: int) -> str:
            calls.append((left, right, speed_limit))
            return "fake"

        self.context.esp32.drive_tank = fake_drive  # type: ignore[method-assign]
        self.context.settings.maneuvers.manual_turn_min_speed_limit = 95

        status, body = self.post_json(
            "/api/control/tank",
            {"left": 0.7, "right": -0.7, "speed_limit": 35, "seq": 2},
        )

        self.assertEqual(status, 200)
        self.assertIn('"effective_speed_limit": 95', body)
        self.assertEqual(calls, [(0.7, -0.7, 95)])
        self.assertEqual(self.context.state.snapshot()["control"]["speed_limit"], 35)

    def test_low_speed_straight_drive_does_not_boost_speed(self) -> None:
        calls: list[tuple[float, float, int]] = []

        def fake_drive(left: float, right: float, speed_limit: int) -> str:
            calls.append((left, right, speed_limit))
            return "fake"

        self.context.esp32.drive_tank = fake_drive  # type: ignore[method-assign]

        status, body = self.post_json(
            "/api/control/tank",
            {"left": 0.5, "right": 0.5, "speed_limit": 35, "seq": 3},
        )

        self.assertEqual(status, 200)
        self.assertIn('"effective_speed_limit": 35', body)
        self.assertEqual(calls, [(0.5, 0.5, 35)])

    def test_invalid_boolean_returns_400(self) -> None:
        status, body = self.post_json("/api/control/auto-spray", {"enabled": "maybe"})

        self.assertEqual(status, 400)
        self.assertIn('"error": "bad_request"', body)

    def test_autonomy_plan_api_accepts_available_pump(self) -> None:
        status, body = self.post_json(
            "/api/autonomy/plan",
            {
                "name": "left spray demo",
                "speed_limit": 180,
                "segments": [
                    {"label": "left pump", "left": 0.0, "right": 0.0, "seconds": 0.1, "pump": "left"}
                ],
            },
        )

        self.assertEqual(status, 200)
        self.assertIn('"pump": "left"', body)

    def test_autonomy_plan_rejects_unavailable_pump(self) -> None:
        status, body = self.post_json(
            "/api/autonomy/plan",
            {
                "name": "front spray demo",
                "speed_limit": 180,
                "segments": [
                    {"label": "front pump", "left": 0.0, "right": 0.0, "seconds": 0.1, "pump": "front"}
                ],
            },
        )

        self.assertEqual(status, 400)
        self.assertIn("ishlatib bo'lmaydigan pump", body)

    def test_turn90_route_starts_left_turn(self) -> None:
        plans = []
        self.context.autonomy.start = lambda plan: plans.append(plan)  # type: ignore[method-assign]

        status, body = self.post_json("/api/control/turn90", {"direction": "left"})

        self.assertEqual(status, 200)
        self.assertIn('"direction": "left"', body)
        self.assertEqual(len(plans), 1)
        self.assertGreater(plans[0].segments[0].left, 0)
        self.assertLess(plans[0].segments[0].right, 0)

    def test_turn90_route_applies_trim_and_ramp_compensation(self) -> None:
        plans = []
        self.context.autonomy.start = lambda plan: plans.append(plan)  # type: ignore[method-assign]
        self.context.settings.maneuvers.turn_90_right_seconds = 1.2
        self.context.settings.maneuvers.turn_90_right_trim = 1.1
        self.context.settings.maneuvers.turn_90_ramp_compensation_sec = 0.15

        status, body = self.post_json("/api/control/turn90", {"direction": "right"})

        self.assertEqual(status, 200)
        self.assertIn('"direction": "right"', body)
        self.assertEqual(len(plans), 1)
        self.assertAlmostEqual(plans[0].segments[0].duration_seconds, 1.47, places=2)

    def test_expired_turn90_command_is_ignored(self) -> None:
        plans = []
        self.context.autonomy.start = lambda plan: plans.append(plan)  # type: ignore[method-assign]

        status, body = self.post_json(
            "/api/control/turn90",
            self.expired_command_payload(direction="left", seq=1),
        )

        self.assertEqual(status, 200)
        self.assertIn('"ignored": "expired_command"', body)
        self.assertEqual(plans, [])

    def test_turn90_ignores_stale_manual_drive_while_running(self) -> None:
        drive_calls: list[tuple[float, float, int]] = []

        def fake_start(plan) -> None:  # type: ignore[no-untyped-def]
            self.context.state.update_autonomy(
                running=True,
                status="running",
                current_label=plan.name,
            )

        def fake_drive(left: float, right: float, speed_limit: int) -> str:
            drive_calls.append((left, right, speed_limit))
            return "fake"

        self.context.autonomy.start = fake_start  # type: ignore[method-assign]
        self.context.esp32.drive_tank = fake_drive  # type: ignore[method-assign]

        status, body = self.post_json("/api/control/turn90", {"direction": "left"})
        self.assertEqual(status, 200)

        status, body = self.post_json(
            "/api/control/tank",
            {"left": 1.0, "right": 1.0, "speed_limit": 120, "seq": 10},
        )

        self.assertEqual(status, 200)
        self.assertIn('"ignored": "turn90_running"', body)
        self.assertEqual(drive_calls, [])

    def test_bad_json_returns_400(self) -> None:
        request = Request(
            f"{self.base_url}/api/control/tank",
            data=b'{"left":',
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=3)

        self.assertEqual(context.exception.code, 400)
        body = context.exception.read().decode("utf-8")
        self.assertIn('"error": "bad_json"', body)

    def test_invalid_tank_value_returns_400(self) -> None:
        request = Request(
            f"{self.base_url}/api/control/tank",
            data=b'{"left":"abc","right":0}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=3)

        self.assertEqual(context.exception.code, 400)
        body = context.exception.read().decode("utf-8")
        self.assertIn('"error": "bad_request"', body)


if __name__ == "__main__":
    unittest.main()
