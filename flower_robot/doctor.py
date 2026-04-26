from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import cv2

from flower_robot.camera_sources import resolve_camera_source
from flower_robot.config import AppSettings, SUPPORTED_PUMP_ZONES
from flower_robot.paths import resource_path
from flower_robot.serial_ports import resolve_serial_port, serial_port_candidates


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str | None = None


def _camera_probe(source: int | str) -> tuple[bool, str]:
    resolved_source = resolve_camera_source(source)
    if isinstance(resolved_source, str) and resolved_source.startswith("/dev/"):
        capture = cv2.VideoCapture(resolved_source, cv2.CAP_V4L2)
    else:
        capture = cv2.VideoCapture(resolved_source)
    try:
        if not capture.isOpened():
            return False, f"resolved={resolved_source} | kamera ochilmadi"
        ret, frame = capture.read()
        if not ret or frame is None:
            return False, f"resolved={resolved_source} | frame olinmadi"
        return True, f"resolved={resolved_source} | ok {frame.shape[1]}x{frame.shape[0]}"
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


def _serial_probe(port: str, baudrate: int, timeout: float) -> tuple[bool, str]:
    resolved_port = resolve_serial_port(port)
    if resolved_port is None:
        candidates = serial_port_candidates()
        detail = (
            f"serial_port={port or 'auto'} | kandidatlar: {', '.join(candidates)}"
            if candidates
            else f"serial_port={port or 'auto'} | USB serial port topilmadi"
        )
        return False, detail

    try:
        import serial
    except ImportError:
        return False, "pyserial o'rnatilmagan"

    try:
        with serial.Serial(
            port=resolved_port,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=timeout,
        ) as handle:
            time_to_wait = min(max(timeout, 0.1), 1.0)
            time.sleep(time_to_wait)
            handle.reset_input_buffer()
            handle.write(b"STATUS\n")
            handle.flush()
            payload = handle.readline().decode("utf-8", errors="ignore").strip()
        detail = payload[:140] or "serial javob bo'sh"
        return bool(payload), f"{resolved_port} | {detail}"
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
            detail=f"chel track margin {lane_margin:.2f} cm",
            fix="Robot eni chel ustidagi xavfsiz yurish track'idan katta bo'lib qolgan."
            if lane_margin <= 0
            else None,
        )
    )
    results.append(
        CheckResult(
            name="geometry-reference",
            ok=True,
            detail=f"reference margin {lane_margin:.2f} cm",
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

    mapping_errors = [
        f"{camera}->{pump}"
        for camera, pumps in settings.auto_spray.camera_to_pump.items()
        for pump in pumps
        if pump not in SUPPORTED_PUMP_ZONES
    ]
    if mapping_errors:
        mapping_detail = ", ".join(mapping_errors)
    elif settings.auto_spray.pump_zones:
        mapping_detail = ", ".join(settings.auto_spray.pump_zones)
    else:
        mapping_detail = "pump mapping topilmadi"
    results.append(
        CheckResult(
            name="spray-mapping",
            ok=bool(settings.auto_spray.pump_zones) and not mapping_errors,
            detail=mapping_detail,
            fix="camera_to_pump ichida kamida bitta qo'llab-quvvatlanadigan kanal bo'lishi kerak: left, front yoki right."
            if mapping_errors or not settings.auto_spray.pump_zones
            else None,
        )
    )

    detect_camera_names = [
        camera.name for camera in settings.cameras if camera.enabled and camera.detect_flowers
    ]
    results.append(
        CheckResult(
            name="detect-cameras",
            ok=bool(detect_camera_names),
            detail=", ".join(detect_camera_names) if detect_camera_names else "enabled detect camera yo'q",
            fix="Kamida bitta kamera detect_flowers=true bo'lishi kerak."
            if not detect_camera_names
            else None,
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
        if settings.esp32.transport == "serial":
            esp_ok, esp_detail = _serial_probe(
                settings.esp32.serial_port,
                settings.esp32.baudrate,
                settings.esp32.serial_timeout_sec,
            )
            fix = "ESP32 USB kabeli, serial_port va pyserial ni tekshiring."
        else:
            status_path = "/api/status" if settings.esp32.firmware_mode == "advanced" else "/"
            esp_ok, esp_detail = _http_probe(
                f"{settings.esp32.base_url.rstrip('/')}{status_path}",
                timeout=settings.esp32.timeout_sec,
            )
            fix = "ESP32 power, Wi-Fi va base_url ni tekshiring."
        results.append(
            CheckResult(
                name="esp32",
                ok=esp_ok,
                detail=esp_detail,
                fix=fix if not esp_ok else None,
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
