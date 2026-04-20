from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import cv2

from flower_robot.config import AppSettings
from flower_robot.paths import resource_path


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str | None = None


def _camera_probe(source: int | str) -> tuple[bool, str]:
    capture = cv2.VideoCapture(source)
    try:
        if not capture.isOpened():
            return False, "kamera ochilmadi"
        ret, frame = capture.read()
        if not ret or frame is None:
            return False, "frame olinmadi"
        return True, f"ok {frame.shape[1]}x{frame.shape[0]}"
    finally:
        capture.release()


def _http_probe(url: str, timeout: float) -> tuple[bool, str]:
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = response.read(300).decode("utf-8", errors="ignore")
        return True, payload[:140]
    except URLError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def run_doctor(
    settings: AppSettings,
    as_json: bool = False,
    skip_cameras: bool = False,
    skip_esp32: bool = False,
) -> int:
    results: list[CheckResult] = []

    config_exists = settings.config_path.exists()
    results.append(
        CheckResult(
            name="config",
            ok=config_exists,
            detail=str(settings.config_path),
            fix="config.json fayli loyiha ildizida bo'lishi kerak." if not config_exists else None,
        )
    )

    model_path = Path(settings.vision.model_path)
    results.append(
        CheckResult(
            name="model",
            ok=model_path.exists(),
            detail=str(model_path),
            fix="YOLO model faylini shu manzilga qo'ying." if not model_path.exists() else None,
        )
    )

    static_root = resource_path("flower_robot", "static")
    for file_name in ("index.html", "style.css", "app.js"):
        asset = static_root / file_name
        results.append(
            CheckResult(
                name=f"asset:{file_name}",
                ok=asset.exists(),
                detail=str(asset),
                fix=f"{file_name} topilmadi." if not asset.exists() else None,
            )
        )

    lane_margin = settings.measurements.lane_margin_cm
    results.append(
        CheckResult(
            name="geometry",
            ok=lane_margin > 0,
            detail=f"lane margin {lane_margin:.2f} cm",
            fix="Robot eni yo'lakdan katta bo'lib qolgan." if lane_margin <= 0 else None,
        )
    )
    results.append(
        CheckResult(
            name="geometry-warning",
            ok=lane_margin > 2.5,
            detail=f"tor yo'lak: har tomonda {lane_margin:.2f} sm zaxira",
            fix="Avtonom uchun yon sensor + encoder + IMU tavsiya qilinadi." if lane_margin <= 2.5 else None,
        )
    )

    if settings.auto_spray.default_enabled and settings.esp32.firmware_mode != "advanced":
        results.append(
            CheckResult(
                name="auto-spray-mode",
                ok=False,
                detail=f"firmware_mode={settings.esp32.firmware_mode}",
                fix="Auto spray uchun advanced ESP32 firmware kerak.",
            )
        )
    else:
        results.append(
            CheckResult(
                name="auto-spray-mode",
                ok=True,
                detail=f"firmware_mode={settings.esp32.firmware_mode}",
            )
        )

    enabled_cameras = [camera for camera in settings.cameras if camera.enabled]
    if skip_cameras:
        results.append(
            CheckResult(
                name="cameras-skipped",
                ok=True,
                detail="kamera probe build/smoke test uchun o'tkazib yuborildi",
            )
        )
    else:
        if not enabled_cameras:
            results.append(
                CheckResult(
                    name="cameras",
                    ok=False,
                    detail="enabled cameras: 0",
                    fix="Kamida bitta kamerani yoqing.",
                )
            )
        for camera in enabled_cameras:
            ok, detail = _camera_probe(camera.source)
            results.append(
                CheckResult(
                    name=f"camera:{camera.name}",
                    ok=ok,
                    detail=f"source={camera.source} | {detail}",
                    fix=f"{camera.name} kamera source qiymatini tekshiring." if not ok else None,
                )
            )

    if skip_esp32:
        results.append(
            CheckResult(
                name="esp32-skipped",
                ok=True,
                detail="ESP32 probe build/smoke test uchun o'tkazib yuborildi",
            )
        )
    else:
        status_path = "/api/status" if settings.esp32.firmware_mode == "advanced" else "/"
        esp_ok, esp_detail = _http_probe(
            f"{settings.esp32.base_url.rstrip('/')}{status_path}",
            timeout=settings.esp32.timeout_sec,
        )
        results.append(
            CheckResult(
                name="esp32",
                ok=esp_ok,
                detail=esp_detail,
                fix="ESP32 power, Wi-Fi va base_url ni tekshiring." if not esp_ok else None,
            )
        )

    if as_json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        print("Flower Rover Doctor")
        for result in results:
            is_warning = result.name.endswith("warning")
            if result.ok:
                status = "OK  "
            elif is_warning:
                status = "WARN"
            else:
                status = "FAIL"
            print(f"[{status}] {result.name}: {result.detail}")
            if result.fix:
                print(f"       fix: {result.fix}")

    hard_fail = any(
        (not result.ok) and not result.name.endswith("warning")
        for result in results
    )
    return 1 if hard_fail else 0
