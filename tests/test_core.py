from __future__ import annotations

import time
import unittest

from flower_robot.auto_spray import AutoSprayController
from flower_robot.autonomy import build_mission_plan
from flower_robot.config import load_settings
from flower_robot.state import RobotStateStore
from flower_robot.vision import DetectionResult


class FakeESP32:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def set_pump(self, side: str, enabled: bool) -> None:
        self.calls.append((side, enabled))


class FlowerRobotCoreTests(unittest.TestCase):
    def test_config_loads(self) -> None:
        settings = load_settings()
        self.assertEqual(settings.esp32.firmware_mode, "advanced")
        self.assertGreater(settings.measurements.lane_margin_cm, 0)

    def test_mission_plan_converts_meters(self) -> None:
        settings = load_settings()
        plan = build_mission_plan(
            {
                "name": "demo",
                "speed_limit": 180,
                "segments": [{"label": "row", "left": 0.5, "right": 0.5, "meters": 7.0}],
            },
            settings.measurements,
        )
        self.assertEqual(plan.name, "demo")
        self.assertGreater(plan.total_seconds, 0)
        self.assertAlmostEqual(plan.total_distance_m, 7.0)

    def test_auto_spray_pulses_expected_pump(self) -> None:
        settings = load_settings()
        state = RobotStateStore(settings)
        state.update_control(auto_spray=True)
        fake_esp = FakeESP32()
        controller = AutoSprayController(settings.auto_spray, fake_esp, state)
        controller.maybe_trigger(
            "left",
            DetectionResult(
                detections=1,
                last_detection={"centered": True},
                centered_detection={"centered": True},
            ),
        )
        time.sleep((settings.auto_spray.pulse_ms / 1000.0) + 0.1)
        self.assertEqual(fake_esp.calls, [("left", True), ("left", False)])
        self.assertEqual(state.snapshot()["spray"]["last_pump"], "left")


if __name__ == "__main__":
    unittest.main()
