from __future__ import annotations

import time
import unittest

from flower_robot.auto_spray import AutoSprayController
from flower_robot.autonomy import MissionController, build_mission_plan
from flower_robot.config import load_settings
from flower_robot.esp32_client import ESP32Client
from flower_robot.state import RobotStateStore
from flower_robot.vision import DetectionResult


class FakeESP32:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.drive_calls: list[tuple[float, float, int]] = []
        self.stop_count = 0

    def set_pump(self, side: str, enabled: bool) -> None:
        self.calls.append((side, enabled))

    def drive_tank(self, left: float, right: float, speed_limit: int) -> str:
        self.drive_calls.append((left, right, speed_limit))
        return "fake"

    def stop(self) -> None:
        self.stop_count += 1


class FakeSerialPort:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = responses
        self.writes: list[bytes] = []
        self.is_open = True

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def readline(self) -> bytes:
        if self.responses:
            return self.responses.pop(0)
        return b'{"ok":true,"pumps":{"left":false,"front":false,"right":false}}\n'

    def reset_input_buffer(self) -> None:
        return None

    def reset_output_buffer(self) -> None:
        return None

    def close(self) -> None:
        self.is_open = False


class FlowerRobotCoreTests(unittest.TestCase):
    def test_config_loads(self) -> None:
        settings = load_settings()
        self.assertEqual(settings.esp32.transport, "serial")
        self.assertEqual(settings.esp32.firmware_mode, "advanced")
        self.assertGreater(settings.measurements.lane_margin_cm, 0)

    def test_serial_esp32_client_protocol(self) -> None:
        settings = load_settings()
        settings.esp32.transport = "serial"
        settings.esp32.serial_ready_delay_sec = 0.0
        state = RobotStateStore(settings)
        fake_port = FakeSerialPort(
            [
                b'{"ok":true,"pumps":{"left":false,"front":true,"right":false}}\n',
                b'{"ok":true}\n',
                b'{"ok":true}\n',
                b'{"ok":true}\n',
            ]
        )
        client = ESP32Client(
            settings.esp32,
            state,
            serial_factory=lambda **_: fake_port,
        )

        client.poll_status()
        mode = client.drive_tank(1.2, -1.2, 999)
        client.set_pump("front", False)
        client.stop()

        self.assertEqual(mode, "serial")
        self.assertEqual(
            fake_port.writes,
            [
                b"STATUS\n",
                b"DRIVE 1.000 -1.000 255\n",
                b"PUMP front off\n",
                b"STOP\n",
            ],
        )
        snapshot = state.snapshot()
        self.assertTrue(snapshot["esp32"]["online"])
        self.assertFalse(snapshot["pumps"]["front"])

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

    def test_mission_plan_clamps_values(self) -> None:
        settings = load_settings()
        plan = build_mission_plan(
            {
                "speed_limit": 999,
                "segments": [{"left": 2.0, "right": -2.0, "seconds": 0.5}],
            },
            settings.measurements,
        )
        self.assertEqual(plan.speed_limit, 255)
        self.assertEqual(plan.segments[0].left, 1.0)
        self.assertEqual(plan.segments[0].right, -1.0)

    def test_mission_plan_requires_time_or_distance(self) -> None:
        settings = load_settings()
        with self.assertRaises(ValueError):
            build_mission_plan(
                {"segments": [{"left": 0.5, "right": 0.5}]},
                settings.measurements,
            )

    def test_autonomy_restart_ignores_old_worker(self) -> None:
        settings = load_settings()
        state = RobotStateStore(settings)
        fake_esp = FakeESP32()
        controller = MissionController(fake_esp, state)  # type: ignore[arg-type]

        slow_plan = build_mission_plan(
            {
                "name": "slow",
                "speed_limit": 120,
                "segments": [{"label": "slow segment", "left": 0.4, "right": 0.4, "seconds": 0.8}],
            },
            settings.measurements,
        )
        fast_plan = build_mission_plan(
            {
                "name": "fast",
                "speed_limit": 150,
                "segments": [{"label": "fast segment", "left": 0.2, "right": 0.2, "seconds": 0.1}],
            },
            settings.measurements,
        )

        controller.start(slow_plan)
        time.sleep(0.05)
        controller.start(fast_plan)
        time.sleep(0.35)

        snapshot = state.snapshot()["autonomy"]
        self.assertEqual(snapshot["plan_name"], "fast")
        self.assertEqual(snapshot["status"], "completed")
        self.assertEqual(snapshot["progress"], 1.0)
        self.assertIn((0.2, 0.2, 150), fake_esp.drive_calls)

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

    def test_front_auto_spray_maps_to_front_pump(self) -> None:
        settings = load_settings()
        state = RobotStateStore(settings)
        state.update_control(auto_spray=True)
        fake_esp = FakeESP32()
        controller = AutoSprayController(settings.auto_spray, fake_esp, state)
        controller.maybe_trigger(
            "front",
            DetectionResult(
                detections=1,
                last_detection={"centered": True},
                centered_detection={"centered": True},
            ),
        )
        time.sleep((settings.auto_spray.pulse_ms / 1000.0) + 0.1)
        self.assertEqual(fake_esp.calls, [("front", True), ("front", False)])
        snapshot = state.snapshot()["spray"]
        self.assertEqual(snapshot["last_pump"], "front")
        self.assertEqual(snapshot["zones"]["front"]["trigger_count"], 1)

    def test_auto_spray_ignores_when_disabled(self) -> None:
        settings = load_settings()
        state = RobotStateStore(settings)
        state.update_control(auto_spray=False)
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
        time.sleep(0.05)
        self.assertEqual(fake_esp.calls, [])

    def test_auto_spray_cooldown_blocks_retrigger(self) -> None:
        settings = load_settings()
        state = RobotStateStore(settings)
        state.update_control(auto_spray=True)
        fake_esp = FakeESP32()
        controller = AutoSprayController(settings.auto_spray, fake_esp, state)
        detection = DetectionResult(
            detections=1,
            last_detection={"centered": True},
            centered_detection={"centered": True},
        )

        controller.maybe_trigger("right", detection)
        controller.maybe_trigger("right", detection)
        time.sleep((settings.auto_spray.pulse_ms / 1000.0) + 0.1)

        self.assertEqual(fake_esp.calls, [("right", True), ("right", False)])
        self.assertEqual(state.snapshot()["spray"]["zones"]["right"]["trigger_count"], 1)


if __name__ == "__main__":
    unittest.main()
