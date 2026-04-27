from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from flower_robot.config import MeasurementsConfig
from flower_robot.esp32_client import ESP32Client
from flower_robot.state import RobotStateStore

SPRAY_ZONES = {"left", "front", "right"}
AUTONOMY_DRIVE_KEEPALIVE_SEC = 0.25


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class MissionSegment:
    label: str
    left: float
    right: float
    duration_seconds: float
    distance_m: float = 0.0
    pump: str | None = None


@dataclass
class MissionPlan:
    name: str
    speed_limit: int
    segments: list[MissionSegment]
    warnings: list[str]

    @property
    def total_seconds(self) -> float:
        return round(sum(segment.duration_seconds for segment in self.segments), 2)

    @property
    def total_distance_m(self) -> float:
        return round(sum(segment.distance_m for segment in self.segments), 2)


def build_mission_plan(payload: dict[str, Any], measurements: MeasurementsConfig) -> MissionPlan:
    name = str(payload.get("name") or "Agro Mission").strip()
    speed_limit = int(_clamp(float(payload.get("speed_limit", 180)), 0, 255))
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("Kamida bitta segment kiriting.")

    warnings: list[str] = [
        "Metr asosidagi avtonom rejim encoder yoki kalibrlashsiz taxminiy ishlaydi."
    ]

    plan_segments: list[MissionSegment] = []
    for index, raw in enumerate(raw_segments, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"{index}-segment noto'g'ri formatda.")

        label = str(raw.get("label") or f"Segment {index}").strip()
        left = _clamp(float(raw.get("left", raw.get("speed", 0.0))), -1.0, 1.0)
        right = _clamp(float(raw.get("right", raw.get("speed", 0.0))), -1.0, 1.0)
        seconds = raw.get("seconds")
        meters = float(raw.get("meters", 0.0))
        pump = raw.get("pump")

        if seconds is None:
            drive_factor = max(abs(left), abs(right), 0.1)
            if meters <= 0:
                raise ValueError(
                    f"{index}-segment uchun 'seconds' yoki musbat 'meters' berilishi kerak."
                )
            seconds = meters / max(measurements.full_speed_mps * drive_factor, 0.05)
        else:
            seconds = float(seconds)

        if seconds <= 0:
            raise ValueError(f"{index}-segment davomiyligi 0 dan katta bo'lishi kerak.")

        plan_segments.append(
            MissionSegment(
                label=label,
                left=left,
                right=right,
                duration_seconds=round(seconds, 2),
                distance_m=max(meters, 0.0),
                pump=pump if pump in SPRAY_ZONES else None,
            )
        )

    return MissionPlan(name=name, speed_limit=speed_limit, segments=plan_segments, warnings=warnings)


class MissionController:
    def __init__(self, client: ESP32Client, state: RobotStateStore) -> None:
        self._client = client
        self._state = state
        self._plan: MissionPlan | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._generation = 0

    @property
    def current_plan(self) -> MissionPlan | None:
        return self._plan

    def start(self, plan: MissionPlan) -> None:
        with self._lock:
            self._generation += 1
            self._stop_event.set()
        self._client.stop()

        with self._lock:
            self._generation += 1
            self._plan = plan
            self._stop_event = threading.Event()
            generation = self._generation
            stop_event = self._stop_event

        self._thread = threading.Thread(
            target=self._run_plan,
            args=(plan, stop_event, generation),
            daemon=True,
        )
        self._thread.start()

    def stop(self, reason: str = "stopped") -> None:
        with self._lock:
            self._generation += 1
            self._stop_event.set()
        self._client.stop()
        self._state.update_autonomy(
            running=False,
            status=reason,
            current_label="",
            remaining_seconds=0.0,
        )

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _run_plan(
        self,
        plan: MissionPlan,
        stop_event: threading.Event,
        generation: int,
    ) -> None:
        total_seconds = max(plan.total_seconds, 0.1)
        elapsed_before_segment = 0.0
        self._state.update_autonomy(
            running=True,
            status="running",
            plan_name=plan.name,
            current_segment=0,
            current_label="",
            progress=0.0,
            remaining_seconds=total_seconds,
            warnings=plan.warnings,
        )

        completed = True
        for index, segment in enumerate(plan.segments, start=1):
            if stop_event.is_set() or not self._is_current(generation):
                completed = False
                break

            self._state.update_autonomy(
                current_segment=index,
                current_label=segment.label,
            )

            if segment.pump:
                self._client.set_pump(segment.pump, True)

            self._client.drive_tank(segment.left, segment.right, plan.speed_limit)
            started_at = time.monotonic()
            last_drive_at = started_at
            while not stop_event.is_set() and self._is_current(generation):
                now = time.monotonic()
                elapsed = now - started_at
                if elapsed >= segment.duration_seconds:
                    break
                if now - last_drive_at >= AUTONOMY_DRIVE_KEEPALIVE_SEC:
                    self._client.drive_tank(segment.left, segment.right, plan.speed_limit)
                    last_drive_at = now
                absolute_elapsed = elapsed_before_segment + elapsed
                self._state.update_autonomy(
                    progress=round(absolute_elapsed / total_seconds, 3),
                    remaining_seconds=round(total_seconds - absolute_elapsed, 1),
                )
                time.sleep(0.1)

            if segment.pump and self._is_current(generation):
                self._client.set_pump(segment.pump, False)

            elapsed_before_segment += segment.duration_seconds
            if self._is_current(generation):
                self._client.stop()

        if not self._is_current(generation):
            return

        self._client.stop()
        self._state.update_autonomy(
            running=False,
            status="completed" if completed and not stop_event.is_set() else "manual override",
            progress=1.0 if completed else self._state.snapshot()["autonomy"]["progress"],
            current_label="",
            remaining_seconds=0.0,
        )
