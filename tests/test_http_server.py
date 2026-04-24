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
