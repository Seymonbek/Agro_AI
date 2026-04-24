from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flower_robot.paths import resource_path, runtime_root


SUPPORTED_PUMP_ZONES = ("left", "front", "right")


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8765


@dataclass
class Esp32Config:
    transport: str = "serial"
    base_url: str = "http://192.168.4.1"
    timeout_sec: float = 1.2
    firmware_mode: str = "legacy"
    serial_port: str = "auto"
    baudrate: int = 115200
    serial_timeout_sec: float = 0.5
    serial_ready_delay_sec: float = 1.0


@dataclass
class MeasurementsConfig:
    lane_width_cm: float = 70.0
    robot_width_cm: float = 65.5
    row_length_m: float = 7.0
    full_speed_mps: float = 0.55

    @property
    def lane_margin_cm(self) -> float:
        return round((self.lane_width_cm - self.robot_width_cm) / 2.0, 2)


@dataclass
class VisionConfig:
    model_path: str = "yolov8s-world.pt"
    confidence: float = 0.3
    imgsz: int = 160
    detect_every_n_frames: int = 3
    stream_width: int = 480
    stream_height: int = 360
    capture_fps: int = 15
    stale_frame_grabs: int = 2
    jpeg_quality: int = 72


@dataclass
class AutoSprayConfig:
    default_enabled: bool = True
    pulse_ms: int = 350
    cooldown_ms: int = 1200
    center_tolerance_px: int = 40
    camera_to_pump: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {"front": ("left", "right")}
    )

    @property
    def pump_zones(self) -> list[str]:
        zones: list[str] = []
        for pumps in self.camera_to_pump.values():
            for pump in pumps:
                if pump not in zones:
                    zones.append(pump)
        return zones


@dataclass
class ManeuverConfig:
    turn_90_speed: float = 0.45
    turn_90_speed_limit: int = 180
    turn_90_left_seconds: float = 1.1
    turn_90_right_seconds: float = 1.1


@dataclass
class CameraConfig:
    name: str
    source: int | str
    enabled: bool = True
    detect_flowers: bool = False


@dataclass
class AppSettings:
    server: ServerConfig
    esp32: Esp32Config
    measurements: MeasurementsConfig
    vision: VisionConfig
    auto_spray: AutoSprayConfig
    maneuvers: ManeuverConfig
    cameras: list[CameraConfig]
    config_path: Path


DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"host": "0.0.0.0", "port": 8765},
    "esp32": {
        "transport": "serial",
        "base_url": "http://192.168.4.1",
        "timeout_sec": 1.2,
        "firmware_mode": "advanced",
        "serial_port": "auto",
        "baudrate": 115200,
        "serial_timeout_sec": 0.5,
        "serial_ready_delay_sec": 1.0,
    },
    "measurements": {
        "lane_width_cm": 70.0,
        "robot_width_cm": 65.5,
        "row_length_m": 7.0,
        "full_speed_mps": 0.55,
    },
    "vision": {
        "model_path": "yolov8s-world.pt",
        "confidence": 0.3,
        "imgsz": 160,
        "detect_every_n_frames": 3,
        "stream_width": 480,
        "stream_height": 360,
        "capture_fps": 15,
        "stale_frame_grabs": 2,
        "jpeg_quality": 72,
    },
    "auto_spray": {
        "default_enabled": True,
        "pulse_ms": 350,
        "cooldown_ms": 1200,
        "center_tolerance_px": 40,
        "camera_to_pump": {"front": ["left", "right"]},
    },
    "maneuvers": {
        "turn_90_speed": 0.45,
        "turn_90_speed_limit": 180,
        "turn_90_left_seconds": 1.1,
        "turn_90_right_seconds": 1.1,
    },
    "cameras": [
        {"name": "front", "source": 0, "enabled": True, "detect_flowers": True},
        {"name": "left", "source": 1, "enabled": True, "detect_flowers": False},
        {"name": "right", "source": 2, "enabled": True, "detect_flowers": False},
    ],
}


def _deep_update(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_update(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalise_camera_source(value: int | str) -> int | str:
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _normalise_camera_to_pump(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, tuple[str, ...]] = {}
    for camera_name, raw_pumps in value.items():
        pumps: list[str] = []
        if isinstance(raw_pumps, (list, tuple)):
            candidates = raw_pumps
        else:
            candidates = [raw_pumps]

        for raw_pump in candidates:
            pump_name = str(raw_pump).strip().lower()
            if pump_name and pump_name not in pumps:
                pumps.append(pump_name)

        if pumps:
            normalized[str(camera_name).strip()] = tuple(pumps)
    return normalized


def _resolve_model_path(model_path: str) -> str:
    path = Path(model_path)
    if path.is_absolute():
        return str(path)
    bundled = resource_path(model_path)
    if bundled.exists():
        return str(bundled)
    return str(runtime_root() / model_path)


def load_settings(config_path: Path | None = None) -> AppSettings:
    runtime_config = config_path or runtime_root() / "config.json"
    config_data = DEFAULT_CONFIG
    if runtime_config.exists():
        with runtime_config.open("r", encoding="utf-8") as handle:
            config_data = _deep_update(DEFAULT_CONFIG, json.load(handle))

    server = ServerConfig(**config_data["server"])
    esp32 = Esp32Config(**config_data["esp32"])
    measurements = MeasurementsConfig(**config_data["measurements"])
    vision_dict = dict(config_data["vision"])
    vision_dict["model_path"] = _resolve_model_path(vision_dict["model_path"])
    vision = VisionConfig(**vision_dict)
    auto_spray_dict = dict(config_data["auto_spray"])
    auto_spray_dict["camera_to_pump"] = _normalise_camera_to_pump(
        auto_spray_dict.get("camera_to_pump")
    )
    auto_spray = AutoSprayConfig(**auto_spray_dict)
    maneuvers = ManeuverConfig(**config_data["maneuvers"])
    cameras = [
        CameraConfig(
            name=item["name"],
            source=_normalise_camera_source(item["source"]),
            enabled=item.get("enabled", True),
            detect_flowers=item.get("detect_flowers", False),
        )
        for item in config_data["cameras"]
    ]
    return AppSettings(
        server=server,
        esp32=esp32,
        measurements=measurements,
        vision=vision,
        auto_spray=auto_spray,
        maneuvers=maneuvers,
        cameras=cameras,
        config_path=runtime_config,
    )
