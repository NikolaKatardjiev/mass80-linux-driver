"""Monitor brightness control via DDC/CI (``ddcutil``), driven by the Home
page's "PC Light" slider (``light_computer``).

The device sends ``{"action":"light_computer","value":0-100}`` up to ~30
times/second while the slider is being dragged (confirmed empirically). Each
``ddcutil`` invocation takes ~100-500ms, far too slow to run synchronously
from the serial read loop (it would stall RX processing and desync the
link). Instead, ``set()`` is non-blocking: it just records the latest
requested value and wakes a single background worker thread, which applies
only the most recent value once it's free -- any values superseded while the
worker was still busy are silently dropped (coalesced), matching how a
physical brightness control only cares about "where the slider ended up".

Bus discovery (``ddcutil detect --brief``) happens once, lazily, and is
cached; if a ``setvcp`` call ever fails we assume the display topology
changed (monitor turned off/unplugged, etc) and re-detect before the next
attempt.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
from typing import Callable, Optional

log = logging.getLogger("mass80d.brightness")

VCP_BRIGHTNESS = "10"
DDCUTIL_TIMEOUT = 5.0
# Installed ddcutil (3.0.2, checked via --help) supports --sleep-multiplier;
# shortening DDC's inter-command sleeps noticeably speeds up setvcp/getvcp
# round-trips without (in practice) causing unreliable writes on the tested
# MSI MAG322CQR pair.
SLEEP_MULTIPLIER = "0.2"

_BUS_RE = re.compile(r"I2C bus:\s*/dev/i2c-(\d+)")
_GETVCP_RE = re.compile(r"VCP\s+\S+\s+\S+\s+(\d+)")

RunnerResult = subprocess.CompletedProcess


def _default_runner(args: list[str], timeout: float = DDCUTIL_TIMEOUT) -> RunnerResult:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def parse_detect_buses(output: str) -> list[int]:
    """Parse ``ddcutil detect --brief`` output into a list of I2C bus numbers.

    Sample input (confirmed on this system, two MSI MAG322CQR displays)::

        Display 1
           I2C bus:          /dev/i2c-11
           DRM connector:    card1-HDMI-A-2
           ...
        Display 2
           I2C bus:          /dev/i2c-14
           ...
    """
    return [int(m.group(1)) for m in _BUS_RE.finditer(output)]


def parse_getvcp_value(output: str) -> Optional[int]:
    """Parse ``ddcutil getvcp 10 --brief`` output, e.g. ``VCP 10 C 100 100``."""
    m = _GETVCP_RE.search(output)
    if not m:
        return None
    return int(m.group(1))


def _clamp(value: int) -> int:
    return max(0, min(100, value))


class BrightnessProvider:
    """Coalescing, non-blocking DDC/CI brightness setter + cached query."""

    def __init__(self, enabled: bool = True, buses: Optional[list[int]] = None,
                 runner: Callable[[list[str]], RunnerResult] = _default_runner,
                 ddcutil_path: str = "ddcutil"):
        self._enabled = enabled
        self._configured_buses = list(buses) if buses else None
        self._runner = runner
        self._ddcutil = ddcutil_path

        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._pending: Optional[int] = None
        self._stop = False
        self._buses: Optional[list[int]] = None

        self._query_cache: Optional[int] = None
        self._query_inflight = False

        self._worker: Optional[threading.Thread] = None

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if not self._enabled:
            return
        with self._lock:
            if self._worker is not None:
                return
            self._stop = False
            self._worker = threading.Thread(
                target=self._worker_loop, daemon=True, name="brightness-worker"
            )
            self._worker.start()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=DDCUTIL_TIMEOUT + 1.0)

    # -- public API ---------------------------------------------------

    def set(self, value: int) -> None:
        """Record the latest requested brightness; returns immediately."""
        if not self._enabled:
            return
        value = _clamp(int(value))
        self.start()  # lazily ensure the worker is running
        with self._cv:
            self._pending = value
            self._cv.notify()

    def query_cached(self) -> Optional[int]:
        """Return the last known brightness without blocking.

        If nothing is cached yet, kicks off a one-shot background refresh
        and returns None (the *next* query will likely have a value).
        """
        if not self._enabled:
            return None
        with self._lock:
            if self._query_cache is not None:
                return self._query_cache
            if self._query_inflight:
                return None
            self._query_inflight = True
        threading.Thread(target=self._refresh_query_cache, daemon=True,
                          name="brightness-query").start()
        return None

    # -- worker -------------------------------------------------------

    def _worker_loop(self) -> None:
        while True:
            with self._cv:
                while self._pending is None and not self._stop:
                    self._cv.wait()
                if self._stop and self._pending is None:
                    return
                value = self._pending
                self._pending = None
            if value is not None:
                self._apply(value)

    def _apply(self, value: int) -> None:
        buses = self._ensure_buses()
        if not buses:
            log.warning("brightness: no displays detected, dropping set(%d)", value)
            return

        any_failed = False
        for bus in buses:
            if not self._setvcp(bus, value):
                any_failed = True

        if any_failed:
            # Topology may have changed (display off/unplugged); re-detect
            # before the next attempt instead of repeatedly hammering a
            # stale bus list.
            with self._lock:
                self._buses = None
        else:
            # Always force-set the cache from a real applied value: this is
            # authoritative (it's literally what we just told the display),
            # so it must win over anything a concurrent/slower background
            # getvcp refresh (see _refresh_query_cache) might report.
            with self._lock:
                self._query_cache = value

    def _refresh_query_cache(self) -> None:
        value = None
        for bus in self._ensure_buses():
            value = self._getvcp(bus)
            if value is not None:
                break

        with self._lock:
            # Only *fill* an empty cache -- never clobber a value that a
            # (possibly concurrent) real set() already applied. A getvcp
            # readback can lag behind a DDC/CI write we just issued, so if
            # anything populated the cache while this (slow) query was in
            # flight, that's the fresher truth and must be kept.
            if self._query_cache is None:
                self._query_cache = value
            self._query_inflight = False

    # -- bus management -------------------------------------------------

    def _ensure_buses(self) -> list[int]:
        with self._lock:
            if self._buses is not None:
                return self._buses
        buses = self._configured_buses if self._configured_buses is not None else self._detect_buses()
        with self._lock:
            self._buses = buses
        return buses

    def _detect_buses(self) -> list[int]:
        try:
            proc = self._runner([self._ddcutil, "detect", "--brief"])
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("ddcutil detect failed: %s", e)
            return []
        if proc.returncode != 0:
            log.warning("ddcutil detect exited %s: %s", proc.returncode, proc.stderr)
            return []
        buses = parse_detect_buses(proc.stdout)
        log.info("brightness: detected displays on I2C buses %s", buses)
        return buses

    # -- ddcutil invocations ----------------------------------------------

    def _setvcp(self, bus: int, value: int) -> bool:
        args = [
            self._ddcutil, "--bus", str(bus), "setvcp", VCP_BRIGHTNESS, str(value),
            "--noverify", "--sleep-multiplier", SLEEP_MULTIPLIER,
        ]
        try:
            proc = self._runner(args)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("ddcutil setvcp bus %d failed: %s", bus, e)
            return False
        if proc.returncode != 0:
            log.warning("ddcutil setvcp bus %d exited %s: %s", bus, proc.returncode, proc.stderr)
            return False
        return True

    def _getvcp(self, bus: int) -> Optional[int]:
        args = [
            self._ddcutil, "--bus", str(bus), "getvcp", VCP_BRIGHTNESS, "--brief",
            "--sleep-multiplier", SLEEP_MULTIPLIER,
        ]
        try:
            proc = self._runner(args)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("ddcutil getvcp bus %d failed: %s", bus, e)
            return None
        if proc.returncode != 0:
            return None
        return parse_getvcp_value(proc.stdout)
