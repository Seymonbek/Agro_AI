from __future__ import annotations

import cv2
import numpy as np
from ultralytics import YOLOWorld

from flower_robot.config import AppSettings


def run_legacy_dual_camera_demo(settings: AppSettings) -> None:
    left_camera = next((camera for camera in settings.cameras if camera.name == "left"), None)
    right_camera = next((camera for camera in settings.cameras if camera.name == "right"), None)
    if left_camera is None or right_camera is None:
        raise RuntimeError("left va right kameralar config ichida bo'lishi kerak.")

    model = YOLOWorld(settings.vision.model_path)
    model.set_classes(["flower", "artificial plant"])

    cap_left = cv2.VideoCapture(left_camera.source)
    cap_right = cv2.VideoCapture(right_camera.source)

    while True:
        ret_left, frame_left = cap_left.read()
        ret_right, frame_right = cap_right.read()

        if not ret_left or not ret_right:
            print("Kamera uzildi yoki noto'g'ri ulangan. config.json dagi source qiymatini tekshiring.")
            break

        frame_left = cv2.resize(frame_left, (640, 480))
        frame_right = cv2.resize(frame_right, (640, 480))
        height, width, _ = frame_left.shape
        center_x = width // 2

        results = model.predict(
            [frame_left, frame_right],
            conf=settings.vision.confidence,
            imgsz=settings.vision.imgsz,
            verbose=False,
            half=False,
        )

        for frame, result, title, color in (
            (frame_left, results[0], "CHAP KAMERA", (64, 196, 128)),
            (frame_right, results[1], "O'NG KAMERA", (71, 85, 255)),
        ):
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                flower_center_x = int((x1 + x2) / 2)
                flower_center_y = int((y1 + y2) / 2)
                centered = abs(flower_center_x - center_x) < 40

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.circle(frame, (flower_center_x, flower_center_y), 5, color, -1)
                if centered:
                    cv2.putText(
                        frame,
                        "GUL MARKAZDA!",
                        (20, 60),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        color,
                        3,
                    )

            cv2.line(frame, (center_x, 0), (center_x, height), (255, 227, 122), 2)
            cv2.putText(frame, title, (200, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        dashboard = np.hstack((frame_left, frame_right))
        cv2.imshow("AGRO AI - Legacy Dual Camera Demo", dashboard)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap_left.release()
    cap_right.release()
    cv2.destroyAllWindows()
