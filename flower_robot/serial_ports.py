from __future__ import annotations

from pathlib import Path
import sys


AUTO_SERIAL_PORT = "auto"
LINUX_SERIAL_PATTERNS = (
    "/dev/serial/by-id/*",
    "/dev/ttyACM*",
    "/dev/ttyUSB*",
)


def serial_port_candidates() -> list[str]:
    ports: list[str] = []
    seen_targets: set[str] = set()

    try:
        from serial.tools import list_ports
    except Exception:  # noqa: BLE001 - pyserial can be missing during doctor checks.
        list_ports = None

    if list_ports is not None:
        for port in list_ports.comports():
            device = getattr(port, "device", None)
            description = getattr(port, "description", "")
            hwid = getattr(port, "hwid", "")
            if device and _is_likely_controller_port(device, description, hwid):
                _add_candidate(ports, seen_targets, Path(device))

    for pattern in LINUX_SERIAL_PATTERNS:
        for path in sorted(Path("/").glob(pattern.lstrip("/"))):
            _add_candidate(ports, seen_targets, path)

    return ports


def resolve_serial_port(configured_port: str | None) -> str | None:
    port = (configured_port or "").strip()
    if port and port.lower() != AUTO_SERIAL_PORT:
        return port

    candidates = serial_port_candidates()
    return candidates[0] if candidates else None


def _add_candidate(ports: list[str], seen_targets: set[str], path: Path) -> None:
    try:
        target = str(path.resolve())
    except Exception:  # noqa: BLE001 - broken device symlinks are possible.
        target = str(path)

    if target in seen_targets:
        return
    seen_targets.add(target)
    ports.append(str(path))


def _is_likely_controller_port(device: str, description: str, hwid: str) -> bool:
    normalized = device.lower()
    if normalized.startswith(("/dev/ttyusb", "/dev/ttyacm", "/dev/cu.usb")):
        return True
    if sys.platform.startswith("win") and normalized.startswith("com"):
        return True

    haystack = f"{description} {hwid}".lower()
    usb_keywords = ("usb", "cp210", "ch340", "wch", "silicon labs", "arduino", "esp32")
    return any(keyword in haystack for keyword in usb_keywords)
