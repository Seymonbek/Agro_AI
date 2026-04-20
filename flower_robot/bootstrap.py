from __future__ import annotations

import shutil
from pathlib import Path

from flower_robot.paths import ensure_local_cache_dirs, resource_path, runtime_root


def ensure_runtime_config(config_path: Path | None = None) -> Path:
    ensure_local_cache_dirs()
    target = config_path or (runtime_root() / "config.json")
    if target.exists():
        return target

    bundled_example = resource_path("config.example.json")
    runtime_example = runtime_root() / "config.example.json"

    source: Path | None = None
    if bundled_example.exists():
        source = bundled_example
    elif runtime_example.exists():
        source = runtime_example

    if source is not None:
        shutil.copyfile(source, target)

    return target
