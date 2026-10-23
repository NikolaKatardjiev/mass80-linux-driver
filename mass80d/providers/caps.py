"""Caps Lock LED state, read from sysfs.

We prefer the LED belonging to the Mass80 keyboard itself (USB VID 4d57:0080
per docs/PROTOCOL.md), falling back to any capslock LED on the system so the
daemon still reports *something* sensible when run on a dev box without the
real keyboard attached.
"""
from __future__ import annotations

import glob
import logging
import os
import time

log = logging.getLogger("mass80d.caps")

KBD_VID, KBD_PID = "4d57", "0080"

_LED_GLOB = "/sys/class/leds/input*::capslock/brightness"


def _led_belongs_to_mass80(led_path: str) -> bool:
    """Best-effort check that a capslock LED node belongs to the Mass80 keyboard."""
    try:
        real = os.path.realpath(led_path)
        # .../leds/inputNN::capslock/brightness -> walk up to the input device,
        # then to its parent USB interface/device to read idVendor/idProduct.
        node = os.path.dirname(real)
        for _ in range(8):
            vid_path = os.path.join(node, "idVendor")
            pid_path = os.path.join(node, "idProduct")
            if os.path.exists(vid_path) and os.path.exists(pid_path):
                vid = open(vid_path).read().strip()
                pid = open(pid_path).read().strip()
                return (vid, pid) == (KBD_VID, KBD_PID)
            parent = os.path.dirname(node)
            if parent == node:
                break
            node = parent
    except OSError:
        pass
    return False


def find_capslock_led() -> str | None:
    """Return path to the preferred capslock LED brightness file, if any."""
    candidates = sorted(glob.glob(_LED_GLOB))
    if not candidates:
        return None
    for path in candidates:
        if _led_belongs_to_mass80(path):
            return path
    # Fallback: any capslock LED.
    return candidates[0]


class CapsProvider:
    """Reads the current Caps Lock LED state (True/False)."""

    def __init__(self) -> None:
        self._led_path = find_capslock_led()
        if self._led_path is None:
            log.info("no capslock LED found on this system")
        else:
            log.info("using capslock LED %s", self._led_path)

    def refresh(self) -> None:
        """Re-scan for the LED path (devices can appear/disappear)."""
        self._led_path = find_capslock_led()

    def read(self) -> bool:
        if self._led_path is None:
            # Keyboard was replugged (LED path changes); rescan at most every 5s.
            now = time.monotonic()
            if now - getattr(self, "_last_scan", 0.0) < 5.0:
                return False
            self._last_scan = now
            self.refresh()
            if self._led_path is None:
                return False
        try:
            with open(self._led_path) as f:
                return f.read().strip() != "0"
        except OSError:
            self._led_path = None
            return False
