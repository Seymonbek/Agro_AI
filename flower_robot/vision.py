from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from flower_robot.camera_sources import resolve_camera_source
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
            self._model.set_classes(settings.vision.detection_classes)
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
        center_y = view.shape[0] // 2
        cv2.line(view, (0, center_y), (view.shape[1], center_y), (255, 214, 102), 2)

        detections: list[dict[str, Any]] = []
        centered_detection: dict[str, Any] | None = None
        best_detection: dict[str, Any] | None = None

        detections.extend(
            self._annotate_results(
                view,
                self._predict(view, self._settings.vision.confidence),
                offset_x=0,
                offset_y=0,
                source="full",
            )
        )

        if not detections and self._settings.vision.center_crop_fallback:
            crop, offset_x, offset_y = self._center_crop(view)
            if crop.size:
                detections.extend(
                    self._annotate_results(
                        view,
                        self._predict(crop, self._settings.vision.fallback_confidence),
                        offset_x=offset_x,
                        offset_y=offset_y,
                        source="center",
                    )
                )

        if not detections:
            return view, DetectionResult(detections=0, last_detection=None, centered_detection=None)

        for detection in detections:
            if best_detection is None or detection["confidence"] > best_detection["confidence"]:
                best_detection = detection
            if detection["centered"] and centered_detection is None:
                centered_detection = detection

        last_detection = centered_detection or best_detection
        return view, DetectionResult(
            detections=len(detections),
            last_detection=last_detection,
            centered_detection=centered_detection,
        )

    def _predict(self, image: np.ndarray, confidence: float) -> list[Any]:
        with self._lock:
            return self._model.predict(
                image,
                conf=confidence,
                imgsz=self._settings.vision.imgsz,
                verbose=False,
                half=False,
            )

    def _center_crop(self, view: np.ndarray) -> tuple[np.ndarray, int, int]:
        ratio = min(max(float(self._settings.vision.center_crop_ratio), 0.35), 0.95)
        height, width = view.shape[:2]
        crop_width = max(int(width * ratio), 1)
        crop_height = max(int(height * ratio), 1)
        x1 = max((width - crop_width) // 2, 0)
        y1 = max((height - crop_height) // 2, 0)
        x2 = min(x1 + crop_width, width)
        y2 = min(y1 + crop_height, height)
        return view[y1:y2, x1:x2], x1, y1

    def _annotate_results(
        self,
        view: np.ndarray,
        results: list[Any],
        offset_x: int,
        offset_y: int,
        source: str,
    ) -> list[dict[str, Any]]:
        if not results:
            return []

        class_names = self._class_names(results[0])
        center_y = view.shape[0] // 2
        detections: list[dict[str, Any]] = []
        for box in results[0].boxes:
            raw_x1, raw_y1, raw_x2, raw_y2 = [int(value) for value in box.xyxy[0].tolist()]
            x1 = max(raw_x1 + offset_x, 0)
            y1 = max(raw_y1 + offset_y, 0)
            x2 = min(raw_x2 + offset_x, view.shape[1] - 1)
            y2 = min(raw_y2 + offset_y, view.shape[0] - 1)
            conf = float(box.conf[0]) if box.conf is not None else 0.0
            class_name = self._box_label(box, class_names)
            object_center_x = int((x1 + x2) / 2)
            object_center_y = int((y1 + y2) / 2)
            offset = object_center_y - center_y
            is_centered = abs(offset) < self._settings.auto_spray.center_tolerance_px
            color = (75, 211, 164) if is_centered else (248, 113, 113)
            cv2.rectangle(view, (x1, y1), (x2, y2), color, 2)
            cv2.circle(view, (object_center_x, object_center_y), 5, color, -1)
            label = f"{class_name} {conf:.2f}"
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
                    "label": class_name,
                    "confidence": round(conf, 2),
                    "offset_px": int(offset),
                    "centered": is_centered,
                    "source": source,
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                }
            )
        return detections

    def _class_names(self, result: Any) -> dict[int, str]:
        names = getattr(result, "names", None) or getattr(self._model, "names", None)
        if isinstance(names, dict):
            return {int(key): str(value) for key, value in names.items()}
        if isinstance(names, list):
            return {index: str(value) for index, value in enumerate(names)}
        return {index: value for index, value in enumerate(self._settings.vision.detection_classes)}

    @staticmethod
    def _box_label(box: Any, names: dict[int, str]) -> str:
        cls = getattr(box, "cls", None)
        if cls is None:
            return "flower"
        try:
            class_index = int(cls[0])
        except (TypeError, ValueError, IndexError):
            return "flower"
        return names.get(class_index, "flower")


class NullDetectionEngine:
    @property
    def enabled(self) -> bool:
        return False

    @property
    def error(self) -> str | None:
        return None

    def annotate(self, frame: np.ndarray) -> tuple[np.ndarray, DetectionResult]:
        return frame, DetectionResult(detections=0, last_detection=None, centered_detection=None)


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
        self._detection_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_jpeg = self._encode_placeholder("Starting...", "Kamera ishga tushmoqda")
        self._last_detection = DetectionResult(detections=0, last_detection=None, centered_detection=None)
        self._detection_busy = False
        self._last_detection_started_at = 0.0

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

    def _open_capture(self) -> cv2.VideoCapture:
        source = resolve_camera_source(self.camera.source)
        if isinstance(source, str) and source.startswith("/dev/"):
            capture = cv2.VideoCapture(source, cv2.CAP_V4L2)
        else:
            capture = cv2.VideoCapture(source)
        fourcc = self._settings.vision.capture_fourcc.strip()
        if fourcc:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc[:4]))
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings.vision.stream_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings.vision.stream_height)
        if self._settings.vision.capture_fps > 0:
            capture.set(cv2.CAP_PROP_FPS, self._settings.vision.capture_fps)
        return capture

    def _read_latest_frame(self, capture: cv2.VideoCapture) -> tuple[bool, np.ndarray | None]:
        grabs = max(int(self._settings.vision.stale_frame_grabs), 0)
        if grabs <= 0:
            return capture.read()

        grabbed = False
        for _ in range(grabs):
            grabbed = capture.grab()
            if not grabbed:
                break

        if grabbed:
            return capture.retrieve()
        return capture.read()

    def _prepare_frame(self, frame: np.ndarray) -> np.ndarray:
        if self.camera.rotate_180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        return cv2.resize(
            frame,
            (self._settings.vision.stream_width, self._settings.vision.stream_height),
        )

    def _should_draw_center_line(self) -> bool:
        return self.camera.name == "front"

    def _encode_placeholder(self, title: str, subtitle: str) -> bytes:
        frame = _placeholder_frame(
            f"{self.camera.name.upper()} CAMERA",
            f"{title} | {subtitle}",
            self._settings.vision.stream_width,
            self._settings.vision.stream_height,
        )
        success, buffer = cv2.imencode(".jpg", frame)
        return buffer.tobytes() if success else b""

    def _should_start_detection(self, frame_number: int) -> bool:
        if not self.camera.detect_flowers or not self._detector.enabled:
            return False
        if frame_number % max(self._settings.vision.detect_every_n_frames, 1) != 0:
            return False

        now = time.monotonic()
        min_interval = max(float(self._settings.vision.detection_min_interval_sec), 0.0)
        with self._detection_lock:
            if self._detection_busy or (now - self._last_detection_started_at) < min_interval:
                return False
            self._detection_busy = True
            self._last_detection_started_at = now
        return True

    def _start_detection(self, frame: np.ndarray) -> None:
        worker = threading.Thread(target=self._run_detection, args=(frame,), daemon=True)
        worker.start()

    def _run_detection(self, frame: np.ndarray) -> None:
        try:
            _, detection = self._detector.annotate(frame)
            self._last_detection = detection
            if self._detection_callback is not None:
                try:
                    self._detection_callback(self.camera.name, detection)
                except Exception:
                    pass
        finally:
            with self._detection_lock:
                self._detection_busy = False

    def _draw_detection_overlay(self, view: np.ndarray) -> None:
        detection = self._last_detection.last_detection
        if not detection:
            return
        bbox = detection.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            return
        try:
            x1, y1, x2, y2 = [int(value) for value in bbox]
        except (TypeError, ValueError):
            return

        is_centered = bool(detection.get("centered"))
        color = (75, 211, 164) if is_centered else (248, 113, 113)
        label = f"{detection.get('label', 'flower')} {float(detection.get('confidence', 0.0)):.2f}"
        cv2.rectangle(view, (x1, y1), (x2, y2), color, 2)
        cv2.circle(view, (int((x1 + x2) / 2), int((y1 + y2) / 2)), 5, color, -1)
        cv2.putText(
            view,
            label,
            (x1, max(20, y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

    def _run_demo(self) -> None:
        width = self._settings.vision.stream_width
        height = self._settings.vision.stream_height
        last_fps_tick = time.monotonic()
        frames_since_tick = 0
        fps = 0.0
        frame_number = 0
        color_by_camera = {
            "front": (68, 190, 255),
            "left": (122, 209, 109),
            "right": (244, 180, 84),
        }
        accent = color_by_camera.get(self.camera.name, (122, 209, 109))

        while not self._stop_event.is_set():
            frame_number += 1
            frames_since_tick += 1
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:] = (20, 31, 27)
            cv2.rectangle(frame, (0, 0), (width, height), (30, 47, 39), -1)
            if self._should_draw_center_line():
                cv2.line(frame, (0, height // 2), (width, height // 2), (255, 214, 102), 2)

            lane_top = width // 2 - 74
            lane_bottom = width // 2 - 150
            cv2.polylines(
                frame,
                [
                    np.array(
                        [
                            [lane_top, 70],
                            [width - lane_top, 70],
                            [width - lane_bottom, height - 40],
                            [lane_bottom, height - 40],
                        ],
                        dtype=np.int32,
                    )
                ],
                isClosed=True,
                color=(65, 92, 73),
                thickness=3,
            )

            flower_x = int((width // 2) + np.sin(frame_number / 18.0) * 90)
            flower_y = int(height * 0.58)
            cv2.circle(frame, (flower_x, flower_y), 34, accent, -1)
            cv2.circle(frame, (flower_x, flower_y), 9, (255, 255, 255), -1)

            now = time.monotonic()
            if now - last_fps_tick >= 1.0:
                fps = frames_since_tick / max(now - last_fps_tick, 0.001)
                frames_since_tick = 0
                last_fps_tick = now

            success, encoded = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), self._settings.vision.jpeg_quality],
            )
            if success:
                with self._frame_lock:
                    self._latest_jpeg = encoded.tobytes()
            self._state.update_camera(
                self.camera.name,
                online=True,
                fps=round(fps, 1),
                detections=0,
                last_detection=None,
                error=None,
            )
            self._stop_event.wait(0.12)

    def _run(self) -> None:
        if isinstance(self.camera.source, str) and self.camera.source.startswith("demo:"):
            self._run_demo()
            return

        capture = self._open_capture()
        last_fps_tick = time.monotonic()
        frames_since_tick = 0
        fps = 0.0
        frame_number = 0
        consecutive_failures = 0
        reopen_after_failures = max(int(self._settings.vision.reopen_after_failures), 1)

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
                capture = self._open_capture()
                continue

            ok, frame = self._read_latest_frame(capture)
            if not ok:
                consecutive_failures += 1
                self._state.update_camera(
                    self.camera.name,
                    online=False,
                    fps=0.0,
                    error="Frame olinmadi",
                )
                with self._frame_lock:
                    self._latest_jpeg = self._encode_placeholder("Signal yo'q", "USB yoki kabelni tekshiring")
                if consecutive_failures >= reopen_after_failures:
                    capture.release()
                    time.sleep(0.4)
                    capture = self._open_capture()
                    consecutive_failures = 0
                time.sleep(1.0)
                continue

            consecutive_failures = 0
            frame_number += 1
            frames_since_tick += 1
            view = self._prepare_frame(frame)

            if self._should_start_detection(frame_number):
                self._start_detection(view.copy())

            if self._should_draw_center_line():
                cv2.line(
                    view,
                    (0, view.shape[0] // 2),
                    (view.shape[1], view.shape[0] // 2),
                    (255, 214, 102),
                    2,
                )
            self._draw_detection_overlay(view)

            now = time.monotonic()
            if now - last_fps_tick >= 1.0:
                fps = frames_since_tick / max(now - last_fps_tick, 0.001)
                frames_since_tick = 0
                last_fps_tick = now

            success, encoded = cv2.imencode(
                ".jpg",
                view,
                [int(cv2.IMWRITE_JPEG_QUALITY), self._settings.vision.jpeg_quality],
            )
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


class VisionHub:
    def __init__(
        self,
        settings: AppSettings,
        state: RobotStateStore,
        detection_callback: callable | None = None,
    ) -> None:
        self._settings = settings
        self._state = state
        enabled_cameras = [camera for camera in settings.cameras if camera.enabled]
        needs_detection = any(camera.detect_flowers for camera in enabled_cameras)
        self._detector = DetectionEngine(settings) if needs_detection else NullDetectionEngine()
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
