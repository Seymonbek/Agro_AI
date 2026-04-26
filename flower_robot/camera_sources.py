from __future__ import annotations

import glob
import os
import sys
from pathlib import Path


INTERNAL_CAMERA_HINTS = (
    "acer",
    "built-in",
    "facetime",
    "integrated",
    "internal",
    "user facing",
)


def _video_name(path: str) -> str:
    device = Path(path).name
    name_path = Path("/sys/class/video4linux") / device / "name"
    try:
        return name_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _looks_internal_camera(path: str) -> bool:
    haystack = f"{path} {_video_name(path)}".lower()
    return any(hint in haystack for hint in INTERNAL_CAMERA_HINTS)


def _linux_external_camera_sources() -> list[str]:
    sources: list[str] = []
    seen: set[str] = set()

    for pattern in ("/dev/v4l/by-path/*video-index0", "/dev/video*"):
        for candidate in sorted(glob.glob(pattern)):
            resolved = os.path.realpath(candidate)
            if resolved in seen or _looks_internal_camera(resolved):
                continue
            seen.add(resolved)
            sources.append(candidate if pattern.startswith("/dev/v4l") else resolved)
    return sources


def _parse_external_index(source: str) -> int | None:
    if not source.startswith("external:"):
        return None
    try:
        index = int(source.split(":", 1)[1])
    except (IndexError, ValueError):
        return None
    return index if index >= 0 else None


def resolve_camera_source(source: int | str) -> int | str:
    if not isinstance(source, str):
        return source

    external_index = _parse_external_index(source.strip().lower())
    if external_index is None:
        return source

    if sys.platform.startswith("linux"):
        candidates = _linux_external_camera_sources()
        if external_index < len(candidates):
            return candidates[external_index]
        return source

    # On Windows/OpenCV, the laptop camera is usually index 0. External camera
    # aliases intentionally start at 1 so the built-in camera is skipped.
    return external_index + 1
