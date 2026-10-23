"""System volume control/query via ``wpctl`` (PipeWire)."""
from __future__ import annotations

import logging
import re
import subprocess

log = logging.getLogger("mass80d.volume")

TIMEOUT = 2.0
_VOLUME_RE = re.compile(r"Volume:\s*([0-9.]+)\s*(\[MUTED\])?")


def get_volume() -> tuple[int, bool]:
    """Return (volume 0-100, muted) for the default audio sink."""
    try:
        proc = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("wpctl get-volume failed: %s", e)
        return 0, False

    m = _VOLUME_RE.search(proc.stdout or "")
    if not m:
        return 0, False
    value = round(float(m.group(1)) * 100)
    muted = m.group(2) is not None
    return max(0, min(100, value)), muted


def set_volume(value: int) -> None:
    value = max(0, min(100, int(value)))
    try:
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value}%"],
            capture_output=True, timeout=TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("wpctl set-volume failed: %s", e)


def toggle_mute() -> None:
    try:
        subprocess.run(
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
            capture_output=True, timeout=TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("wpctl set-mute failed: %s", e)
