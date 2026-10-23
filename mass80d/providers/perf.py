"""System performance metrics for get_performance, via psutil.

Reply shape (confirmed, docs/PROTOCOL.md):
    {"action":"get_performance","cpu_usage":<int %>,"memory_usage":<int %>,
     "cpu_freq":<int MHz>,"cpu_freq_full":<int MHz>,"cpu_temp":<int C>,
     "net_upload":<int>,"net_download":<int>}

Units for net_upload/net_download are unconfirmed by the real firmware, so
they're configurable (default "KB/s"; also accepts "B/s").
"""
from __future__ import annotations

import logging
import time

import psutil

log = logging.getLogger("mass80d.perf")

_PREFERRED_TEMP_LABELS = (
    ("k10temp", "Tctl"),
    ("k10temp", "Tdie"),
    ("coretemp", "Package id 0"),
)


def _read_cpu_temp() -> int:
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return 0
    if not temps:
        return 0

    for chip, label in _PREFERRED_TEMP_LABELS:
        entries = temps.get(chip)
        if not entries:
            continue
        for entry in entries:
            if entry.label == label:
                return round(entry.current)

    # Fallback: first entry found in any sensor group.
    for entries in temps.values():
        if entries:
            return round(entries[0].current)
    return 0


def _read_cpu_freq() -> tuple[int, int]:
    try:
        freq = psutil.cpu_freq()
    except (FileNotFoundError, OSError):
        freq = None
    if freq is None:
        return 0, 0
    current = round(freq.current) if freq.current else 0
    full = round(freq.max) if freq.max else current
    return current, full


class PerformanceProvider:
    """Tracks network counters across calls to compute bytes/sec deltas."""

    def __init__(self, net_unit: str = "KB/s"):
        self._net_unit = net_unit
        self._last_time: float | None = None
        self._last_sent = 0
        self._last_recv = 0

    def _net_rates(self) -> tuple[int, int]:
        try:
            counters = psutil.net_io_counters(pernic=True)
        except OSError:
            return 0, 0

        sent = 0
        recv = 0
        for iface, c in counters.items():
            if iface == "lo" or iface.startswith("lo:"):
                continue
            sent += c.bytes_sent
            recv += c.bytes_recv

        now = time.monotonic()
        if self._last_time is None:
            self._last_time, self._last_sent, self._last_recv = now, sent, recv
            return 0, 0

        dt = now - self._last_time
        if dt <= 0:
            return 0, 0

        up_bps = max(0, (sent - self._last_sent) / dt)
        down_bps = max(0, (recv - self._last_recv) / dt)
        self._last_time, self._last_sent, self._last_recv = now, sent, recv

        if self._net_unit == "B/s":
            return round(up_bps), round(down_bps)
        # default: KB/s
        return round(up_bps / 1024), round(down_bps / 1024)

    def get(self) -> dict:
        try:
            cpu_usage = round(psutil.cpu_percent(interval=None))
        except OSError:
            cpu_usage = 0
        try:
            memory_usage = round(psutil.virtual_memory().percent)
        except OSError:
            memory_usage = 0

        cpu_freq, cpu_freq_full = _read_cpu_freq()
        cpu_temp = _read_cpu_temp()
        net_upload, net_download = self._net_rates()

        return {
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "cpu_freq": cpu_freq,
            "cpu_freq_full": cpu_freq_full,
            "cpu_temp": cpu_temp,
            "net_upload": net_upload,
            "net_download": net_download,
        }
