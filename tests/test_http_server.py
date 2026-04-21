from __future__ import annotations

import threading
import time
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from flower_robot.config import load_settings
from flower_robot.server import AppContext, RequestHandler


class FlowerRobotHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings()
        self.settings.server.host = "127.0.0.1"
        self.settings.server.port = 8891
        self.settings.cameras = []
        self.context = AppContext(self.settings)
        self.context.start_background_tasks()
        handler = partial(RequestHandler, context=self.context)
        self.httpd = ThreadingHTTPServer((self.settings.server.host, self.settings.server.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.2)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.context.stop_background_tasks()
        self.thread.join(timeout=1.0)

    def test_api_config_route(self) -> None:
        with urlopen("http://127.0.0.1:8891/api/config", timeout=3) as response:
            body = response.read().decode("utf-8")
        self.assertIn('"esp32"', body)
        self.assertIn('"server"', body)
        self.assertIn('"front"', body)
        self.assertIn('"spray_zones"', body)

    def test_api_state_route(self) -> None:
        with urlopen("http://127.0.0.1:8891/api/state", timeout=3) as response:
            body = response.read().decode("utf-8")
        self.assertIn('"control"', body)
        self.assertIn('"measurements"', body)

    def test_front_pump_api_route(self) -> None:
        calls: list[tuple[str, bool]] = []
        self.context.esp32.set_pump = lambda side, enabled: calls.append((side, enabled))  # type: ignore[method-assign]

        request = Request(
            "http://127.0.0.1:8891/api/control/pump",
            data=b'{"side":"front","enabled":true}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            body = response.read().decode("utf-8")

        self.assertIn('"ok": true', body)
        self.assertEqual(calls, [("front", True)])


if __name__ == "__main__":
    unittest.main()
