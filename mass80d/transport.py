"""Serial transport: port discovery, framing, and reconnect handling.

Protocol facts (see docs/PROTOCOL.md):
- Device: USB 303a:4003, CDC-ACM -> /dev/ttyACM*.
- Newline-delimited JSON both directions; port must be opened raw (pyserial
  default is already raw, no tty cooking is involved on Linux for ttyACM).
- Firmware also emits non-JSON debug lines (``[CDC-TX] ...``, ``[C0]...``)
  mixed in with -- and sometimes concatenated onto -- real JSON lines; these
  must be tolerated/ignored, not treated as fatal framing errors.
- Device re-enumerates on reboot/theme change -> host must reconnect.
"""
from __future__ import annotations

import glob
import logging
import os
import threading
import time
from typing import Callable, Optional

import serial

log = logging.getLogger("mass80d.transport")

VID, PID = "303a", "4003"


def find_port() -> Optional[str]:
    """Locate the Mass80 screen controller's CDC-ACM device node, if present."""
    for tty in glob.glob("/sys/class/tty/ttyACM*"):
        dev = os.path.realpath(os.path.join(tty, "device"))
        usb = os.path.dirname(dev)
        try:
            vid = open(os.path.join(usb, "idVendor")).read().strip()
            pid = open(os.path.join(usb, "idProduct")).read().strip()
        except OSError:
            continue
        if (vid, pid) == (VID, PID):
            return "/dev/" + os.path.basename(tty)
    return None


class LineSplitter:
    """Incremental newline-delimited JSON line extractor.

    Feed it raw bytes as they arrive; it yields complete, stripped text lines
    (decoded utf-8, errors replaced). Handles partial reads (a line split
    across multiple ``feed()`` calls) and merged reads (multiple lines in one
    chunk), which is how the real device sends data in practice -- JSON
    lines are frequently glued to adjacent firmware debug output.
    """

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[str]:
        self._buf += data
        lines: list[str] = []
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            text = raw.decode("utf-8", "replace").strip()
            if text:
                lines.append(text)
        return lines


def is_json_line(text: str) -> bool:
    """Cheap pre-filter: does this line look like it starts a JSON object?

    Firmware debug noise is never a JSON object by itself, but it can be
    *concatenated* in front of a real JSON message on the same line (see
    live captures), e.g.::

        [C1]mjpeg_ui-20pct,...swdraw-6pct,ipc1-0pct,[CDC-TX] ("action":"get_time","version":"0.13.4")

    We only treat a line as JSON if, once the noise prefix is stripped away,
    it actually contains a ``{``. Real extraction/parsing is left to the
    caller (protocol dispatch), which should look for the last ``{...}``
    substring rather than assume the whole line is clean JSON.
    """
    return "{" in text


def extract_json_candidate(text: str) -> Optional[str]:
    """Pull the last balanced-looking ``{...}`` substring out of a noisy line.

    Returns None if no ``{`` is present at all.
    """
    start = text.rfind("{")
    if start == -1:
        return None
    end = text.rfind("}")
    if end == -1 or end < start:
        return None
    return text[start : end + 1]


class SerialTransport:
    """Owns the serial port: connect/reconnect loop, RX line dispatch, TX lock."""

    BAUD = 115200

    def __init__(self, on_line: Callable[[str], None], log_raw: bool = False,
                 reconnect_delay: float = 0.5):
        self._on_line = on_line
        self._log_raw = log_raw
        self._reconnect_delay = reconnect_delay
        self._ser: Optional[serial.Serial] = None
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._pause_until = 0.0

    def pause_reconnect(self, seconds: float) -> None:
        """Suspend reconnect attempts for a while (used by enter_udisk_mode)."""
        self._pause_until = time.monotonic() + seconds

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass
            self._ser = None

    def stop(self) -> None:
        self._stop.set()
        self.close()

    def send(self, obj: dict) -> None:
        """Serialize and send a JSON object, newline-terminated. Thread-safe."""
        import json

        try:
            line = json.dumps(obj, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            log.exception("failed to serialize outbound message: %r", obj)
            return
        self._write_line(line)

    def _write_line(self, line: str) -> None:
        with self._write_lock:
            ser = self._ser
            if ser is None:
                return
            try:
                ser.write(line.encode("utf-8") + b"\n")
            except Exception as e:  # noqa: BLE001
                log.warning("write failed: %s", e)

    def run(self) -> None:
        """Blocking connect/read loop; call from the main thread or a worker."""
        while not self._stop.is_set():
            now = time.monotonic()
            if now < self._pause_until:
                time.sleep(min(0.5, self._pause_until - now))
                continue
            port = find_port()
            if not port:
                time.sleep(self._reconnect_delay)
                continue
            try:
                ser = serial.Serial(port, self.BAUD, timeout=0.5)
                ser.dtr = True
                ser.rts = True
            except serial.SerialException as e:
                log.warning("open %s failed: %s", port, e)
                time.sleep(self._reconnect_delay)
                continue

            with self._write_lock:
                self._ser = ser
            log.info("connected %s", port)
            splitter = LineSplitter()
            try:
                while not self._stop.is_set():
                    if time.monotonic() < self._pause_until:
                        break
                    # Block for at most `timeout` waiting for the first byte,
                    # then drain whatever else is already buffered.
                    data = ser.read(1)
                    if data and ser.in_waiting:
                        data += ser.read(ser.in_waiting)
                    if not data:
                        continue
                    for text in splitter.feed(data):
                        if self._log_raw:
                            log.debug("RAW: %s", text)
                        if is_json_line(text):
                            candidate = extract_json_candidate(text)
                            if candidate:
                                self._on_line(candidate)
                        # else: pure firmware debug noise, ignored.
            except (serial.SerialException, OSError) as e:
                log.info("disconnected: %s", e)
            finally:
                with self._write_lock:
                    self._ser = None
                try:
                    ser.close()
                except Exception:  # noqa: BLE001
                    pass
            if not self._stop.is_set():
                time.sleep(self._reconnect_delay)
