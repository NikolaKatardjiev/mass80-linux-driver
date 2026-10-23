"""Album art fetching/encoding for get_cover / get_cover_prev / get_cover_next.

Source: MPRIS ``mpris:artUrl`` (``file://`` or ``http(s)://``), center-cropped
to a square and resized to the requested width x height, re-encoded as a
baseline (non-progressive) JPEG at quality 85 and base64-encoded.

The device's RX buffer is capped at 128KB (docs/PROTOCOL.md); we keep the
JSON line comfortably under that by shrinking JPEG quality if needed.
"""
from __future__ import annotations

import base64
import io
import logging
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse, unquote

from PIL import Image, ImageDraw

log = logging.getLogger("mass80d.cover")

FETCH_TIMEOUT = 5.0
JPEG_QUALITY = 85
MIN_JPEG_QUALITY = 40
# Leave generous headroom under the 128KB device RX buffer for the rest of
# the JSON envelope (action/index/field names) and base64 overhead (~4/3x).
MAX_IMAGE_DATA_B64_BYTES = 90_000
CACHE_TTL = 30.0


def _center_crop_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def _fetch_bytes(url: str) -> bytes | None:
    parsed = urlparse(url)
    try:
        if parsed.scheme == "file":
            path = unquote(parsed.path)
            with open(path, "rb") as f:
                return f.read()
        if parsed.scheme in ("http", "https"):
            req = urllib.request.Request(url, headers={"User-Agent": "mass80d"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                return resp.read()
        log.info("unsupported art URL scheme: %r", parsed.scheme)
    except (OSError, urllib.error.URLError, ValueError) as e:
        log.info("failed to fetch art %s: %s", url, e)
    return None


def _encode_jpeg(img: Image.Image, width: int, height: int) -> bytes:
    """Encode `img` cropped/resized to width x height as a size-bounded JPEG."""
    square = _center_crop_square(img.convert("RGB"))
    resized = square.resize((width, height), Image.LANCZOS)

    quality = JPEG_QUALITY
    while True:
        buf = io.BytesIO()
        resized.save(buf, format="JPEG", quality=quality, progressive=False, optimize=True)
        data = buf.getvalue()
        # base64 expands by ~4/3; compare against our budget.
        if len(data) * 4 // 3 <= MAX_IMAGE_DATA_B64_BYTES or quality <= MIN_JPEG_QUALITY:
            return data
        quality -= 15


def make_placeholder(width: int, height: int) -> bytes:
    """A plain dark placeholder JPEG for when no art is available."""
    img = Image.new("RGB", (width, height), (24, 24, 24))
    draw = ImageDraw.Draw(img)
    # A faint center dot so it's visibly not a decode error, without needing fonts.
    r = max(2, min(width, height) // 24)
    cx, cy = width // 2, height // 2
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(60, 60, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, progressive=False)
    return buf.getvalue()


class CoverProvider:
    """Fetches/caches album art and produces encoded replies by URL."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Image.Image | None]] = {}

    def _get_image(self, url: str) -> Image.Image | None:
        with self._lock:
            entry = self._cache.get(url)
            if entry and (time.monotonic() - entry[0]) < CACHE_TTL:
                return entry[1]

        data = _fetch_bytes(url) if url else None
        img: Image.Image | None = None
        if data:
            try:
                img = Image.open(io.BytesIO(data))
                img.load()
            except Exception as e:  # noqa: BLE001 - untrusted image data
                log.info("failed to decode art from %s: %s", url, e)
                img = None

        with self._lock:
            self._cache[url] = (time.monotonic(), img)
        return img

    def get_cover_b64(self, url: str, width: int, height: int) -> str:
        """Return base64 JPEG for the given art URL, or a placeholder."""
        width = max(1, min(width or 480, 1024))
        height = max(1, min(height or 480, 1024))
        img = self._get_image(url) if url else None
        if img is not None:
            try:
                jpeg = _encode_jpeg(img, width, height)
                return base64.b64encode(jpeg).decode("ascii")
            except Exception as e:  # noqa: BLE001
                log.info("failed to encode art: %s", e)
        return base64.b64encode(make_placeholder(width, height)).decode("ascii")
