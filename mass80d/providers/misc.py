"""Misc device-originated commands: open_url and simple log-only actions."""
from __future__ import annotations

import logging
import subprocess
from urllib.parse import urlparse

log = logging.getLogger("mass80d.misc")

TIMEOUT = 5.0
_ALLOWED_SCHEMES = ("http", "https")


def open_url(value: str) -> None:
    """Open a URL with xdg-open; only http(s) is allowed, scheme-less values
    are assumed to be https."""
    if not value or not isinstance(value, str):
        log.warning("open_url: empty/invalid value")
        return

    candidate = value.strip()
    parsed = urlparse(candidate)
    if not parsed.scheme:
        candidate = "https://" + candidate
        parsed = urlparse(candidate)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        log.warning("open_url: rejecting unsupported scheme %r (%r)", parsed.scheme, value)
        return

    try:
        subprocess.run(["xdg-open", candidate], capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("xdg-open failed for %r: %s", candidate, e)
