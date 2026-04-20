# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH)

datas = [
    (str(project_root / "flower_robot" / "static"), "flower_robot/static"),
    (str(project_root / "yolov8s-world.pt"), "."),
    (str(project_root / "config.example.json"), "."),
    (str(project_root / "README.md"), "."),
]
binaries = []
hiddenimports = []

for package_name in ("ultralytics", "cv2", "numpy", "torch", "torchvision", "PIL", "clip"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

clip_weight = Path.home() / ".cache" / "clip" / "ViT-B-32.pt"
if clip_weight.exists():
    datas.append((str(clip_weight), ".cache/clip"))


a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FlowerRoverControl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FlowerRoverControl",
)
