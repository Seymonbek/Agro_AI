from __future__ import annotations

import sys
from pathlib import Path


def bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def ensure_local_cache_dirs() -> None:
    runtime = runtime_root()
    cache_root = runtime / ".cache"
    clip_cache = cache_root / "clip"
    cache_root.mkdir(parents=True, exist_ok=True)
    clip_cache.mkdir(parents=True, exist_ok=True)

    # Keep CLIP/torch caches inside the release folder for portable Windows usage.
    import os

    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root))
    os.environ.setdefault("TORCH_HOME", str(cache_root / "torch"))
