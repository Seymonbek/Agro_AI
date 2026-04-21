from __future__ import annotations

import argparse
import multiprocessing
from pathlib import Path

from flower_robot.bootstrap import ensure_runtime_config
from flower_robot.config import load_settings
from flower_robot.doctor import run_doctor
from flower_robot.legacy_dual_camera_demo import run_legacy_dual_camera_demo
from flower_robot.server import RobotApplication


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Flower rover control center: laptop-based server, vision and autonomy skeleton."
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="serve",
        choices=("serve", "vision-demo", "doctor"),
        help="Run the web control server, the old dual-camera YOLO demo, or doctor checks.",
    )
    parser.add_argument("--host", help="Override server host from config.json.")
    parser.add_argument("--port", type=int, help="Override server port from config.json.")
    parser.add_argument(
        "--config",
        type=Path,
        help="Optional path to config.json. Defaults to ./config.json if present.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Used with doctor mode to print machine-readable JSON.",
    )
    parser.add_argument(
        "--skip-cameras",
        action="store_true",
        help="Used with doctor mode to skip live camera checks.",
    )
    parser.add_argument(
        "--skip-esp32",
        action="store_true",
        help="Used with doctor mode to skip live ESP32 connectivity checks.",
    )
    parser.add_argument(
        "--demo-cameras",
        action="store_true",
        help="Used with serve mode to show safe generated demo camera streams instead of real cameras.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ensure_runtime_config(args.config)
    settings = load_settings(args.config)

    if args.host:
        settings.server.host = args.host
    if args.port:
        settings.server.port = args.port
    if args.demo_cameras:
        settings.auto_spray.default_enabled = False
        for camera in settings.cameras:
            camera.source = f"demo:{camera.name}"
            camera.detect_flowers = False

    if args.mode == "vision-demo":
        run_legacy_dual_camera_demo(settings)
        return
    if args.mode == "doctor":
        raise SystemExit(
            run_doctor(
                settings,
                as_json=args.json,
                skip_cameras=args.skip_cameras,
                skip_esp32=args.skip_esp32,
            )
        )

    app = RobotApplication(settings)
    app.serve_forever()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
