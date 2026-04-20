from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from flower_robot.config import AppSettings, CameraConfig
from flower_robot.state import RobotStateStore

try:
    from ultralytics import YOLOWorld
except Exception:  # noqa: BLE001 - model import is optional at runtime.
    YOLOWorld = None


def _placeholder_frame(title: str, subtitle: str, width: int, height: int) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (26, 39, 34)
    cv2.putText(frame, title, (24, 80), cv2.FONT_HERSHEY_DUPLEX, 1.3, (122, 209, 109), 2)
    cv2.putText(frame, subtitle, (24, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (226, 232, 229), 2)
    cv2.rectangle(frame, (18, 18), (width - 18, height - 18), (72, 109, 88), 2)
    return frame


@dataclass
class DetectionResult:
    detections: int
    last_detection: dict[str, Any] | None
    centered_detection: dict[str, Any] | None


class DetectionEngine:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._model = None
        self._enabled = False
        self._error: str | None = None

        model_path = Path(settings.vision.model_path)
        if YOLOWorld is None:
            self._error = "Ultralytics topilmadi."
            return
        if not model_path.exists():
            self._error = f"Model topilmadi: {model_path}"
            return

        try:
            self._model = YOLOWorld(str(model_path))
            self._model.set_classes(["flower", "artificial plant"])
            self._enabled = True
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def error(self) -> str | None:
        return self._error

    def annotate(self, frame: np.ndarray) -> tuple[np.ndarray, DetectionResult]:
        if not self._enabled or self._model is None:
            return frame, DetectionResult(detections=0, last_detection=None, centered_detection=None)

        view = frame.copy()
        center_x = view.shape[1] // 2
        cv2.line(view, (center_x, 0), (center_x, view.shape[0]), (255, 214, 102), 2)

        detections: list[dict[str, Any]] = []
        centered_detection: dict[str, Any] | None = None
        best_detection: dict[str, Any] | None = None
        with self._lock:
            results = self._model.predict(
                view,
                conf=self._settings.vision.confidence,
                imgsz=self._settings.vision.imgsz,
                verbose=False,
                half=False,
            )

        if not results:
            return view, DetectionResult(detections=0, last_detection=None, centered_detection=None)

        for box in results[0].boxes:
            x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
            conf = float(box.conf[0]) if box.conf is not None else 0.0
            object_center = int((x1 + x2) / 2)
            offset = object_center - center_x
            is_centered = abs(offset) < self._settings.auto_spray.center_tolerance_px
            color = (75, 211, 164) if is_centered else (248, 113, 113)
            cv2.rectangle(view, (x1, y1), (x2, y2), color, 2)
            cv2.circle(view, (object_center, int((y1 + y2) / 2)), 5, color, -1)
            label = f"flower {conf:.2f}"
            cv2.putText(
                view,
                label,
                (x1, max(20, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )
            detections.append(
                {
                    "label": "flower",
                    "confidence": round(conf, 2),
                    "offset_px": int(offset),
                    "centered": is_centered,
                }
            )
            detection = detections[-1]
            if best_detection is None or detection["confidence"] > best_detection["confidence"]:
                best_detection = detection
            if is_centered and centered_detection is None:
                centered_detection = detection

        last_detection = centered_detection or best_detection
        return view, DetectionResult(
            detections=len(detections),
            last_detection=last_detection,
            centered_detection=centered_detection,
        )


class CameraWorker:
    def __init__(
        self,
        camera: CameraConfig,
        settings: AppSettings,
        state: RobotStateStore,
        detector: DetectionEngine,
        detection_callback: callable | None = None,
    ) -> None:
        self.camera = camera
        self._settings = settings
        self._state = state
        self._detector = detector
        self._detection_callback = detection_callback
        self._frame_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_jpeg = self._encode_placeholder("Starting...", "Kamera ishga tushmoqda")
        self._last_detection = DetectionResult(detections=0, last_detection=None, centered_detection=None)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def latest_jpeg(self) -> bytes:
        with self._frame_lock:
            return self._latest_jpeg

    def _encode_placeholder(self, title: str, subtitle: str) -> bytes:
        frame = _placeholder_frame(
            f"{self.camera.name.upper()} CAMERA",
            f"{title} | {subtitle}",
            self._settings.vision.stream_width,
            self._settings.vision.stream_height,
        )
        success, buffer = cv2.imencode(".jpg", frame)
        return buffer.tobytes() if success else b""

    def _run(self) -> None:
        capture = cv2.VideoCapture(self.camera.source)
        last_fps_tick = time.monotonic()
        frames_since_tick = 0
        fps = 0.0
        frame_number = 0

        while not self._stop_event.is_set():
            if not capture.isOpened():
                self._state.update_camera(
                    self.camera.name,
                    online=False,
                    fps=0.0,
                    error="Kamera ochilmadi",
                )
                with self._frame_lock:
                    self._latest_jpeg = self._encode_placeholder("Offline", "Port yoki indeksni tekshiring")
                time.sleep(3.0)
                capture.release()
                capture = cv2.VideoCapture(self.camera.source)
                continue

            ok, frame = capture.read()
            if not ok:
                self._state.update_camera(
                    self.camera.name,
                    online=False,
                    fps=0.0,
                    error="Frame olinmadi",
                )
                with self._frame_lock:
                    self._latest_jpeg = self._encode_placeholder("Signal yo'q", "USB yoki kabelni tekshiring")
                time.sleep(1.0)
                continue

            frame_number += 1
            frames_since_tick += 1
            view = cv2.resize(
                frame,
                (self._settings.vision.stream_width, self._settings.vision.stream_height),
            )

            if (
                self.camera.detect_flowers
                and self._detector.enabled
                and frame_number % max(self._settings.vision.detect_every_n_frames, 1) == 0
            ):
                view, self._last_detection = self._detector.annotate(view)
                if self._detection_callback is not None:
                    try:
                        self._detection_callback(self.camera.name, self._last_detection)
                    except Exception:
                        pass
            else:
                cv2.line(
                    view,
                    (view.shape[1] // 2, 0),
                    (view.shape[1] // 2, view.shape[0]),
                    (255, 214, 102),
                    2,
                )

            now = time.monotonic()
            if now - last_fps_tick >= 1.0:
                fps = frames_since_tick / max(now - last_fps_tick, 0.001)
                frames_since_tick = 0
                last_fps_tick = now

            self._draw_overlay(view, fps)
            success, encoded = cv2.imencode(".jpg", view, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if success:
                with self._frame_lock:
                    self._latest_jpeg = encoded.tobytes()

            self._state.update_camera(
                self.camera.name,
                online=True,
                fps=round(fps, 1),
                detections=self._last_detection.detections,
                last_detection=self._last_detection.last_detection,
                error=self._detector.error if self.camera.detect_flowers and not self._detector.enabled else None,
            )

        capture.release()

    def _draw_overlay(self, frame: np.ndarray, fps: float) -> None:
        cv2.rectangle(frame, (18, 18), (250, 92), (18, 28, 23), -1)
        cv2.putText(
            frame,
            self.camera.name.upper(),
            (30, 45),
            cv2.FONT_HERSHEY_DUPLEX,
            0.9,
            (134, 239, 172),
            2,
        )
        cv2.putText(
            frame,
            f"{fps:.1f} FPS | det={self._last_detection.detections}",
            (30, 76),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (241, 245, 249),
            2,
        )


class VisionHub:
    def __init__(
        self,
        settings: AppSettings,
        state: RobotStateStore,
        detection_callback: callable | None = None,
    ) -> None:
        self._settings = settings
        self._state = state
        self._detector = DetectionEngine(settings)
        self._workers = {
            camera.name: CameraWorker(
                camera,
                settings,
                state,
                self._detector,
                detection_callback=detection_callback,
            )
            for camera in settings.cameras
            if camera.enabled
        }

    @property
    def camera_names(self) -> list[str]:
        return list(self._workers.keys())

    def start(self) -> None:
        for worker in self._workers.values():
            worker.start()

    def stop(self) -> None:
        for worker in self._workers.values():
            worker.stop()

    def get_jpeg(self, camera_name: str) -> bytes | None:
        worker = self._workers.get(camera_name)
        if worker is None:
            return None
        return worker.latest_jpeg()
