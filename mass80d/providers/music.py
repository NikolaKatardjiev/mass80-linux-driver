"""MPRIS music metadata via ``playerctl``.

get_music_info reply shape (confirmed, docs/PROTOCOL.md):
    {"action":"get_music_info","title","artist","progress":<int s>,
     "duration":<int s>,"state":1|0 (int; 1=playing),"index":0}

We shell out to ``playerctl`` rather than talking D-Bus/MPRIS directly to
keep dependencies minimal (playerctl is already an assumed CLI tool). The
device polls this at ~1/s, so results are cached and refreshed at most every
``MIN_REFRESH_INTERVAL`` seconds to keep subprocess overhead low.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time

log = logging.getLogger("mass80d.music")

MIN_REFRESH_INTERVAL = 0.5
PLAYERCTL_TIMEOUT = 1.5

_FORMAT = "{{playerName}}\t{{status}}\t{{title}}\t{{artist}}\t{{mpris:length}}\t{{position}}\t{{mpris:artUrl}}"

_EMPTY = {
    "title": "",
    "artist": "",
    "progress": 0,
    "duration": 0,
    "state": 0,
    "index": 0,
}


def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


class MusicProvider:
    """Caches MPRIS state, preferring a currently-playing player."""

    def __init__(self, preferred_player: str | None = None,
                 min_refresh: float = MIN_REFRESH_INTERVAL):
        self._preferred_player = preferred_player
        self._min_refresh = min_refresh
        self._lock = threading.Lock()
        self._last_fetch = 0.0
        self._cache: dict = dict(_EMPTY)
        self._art_url: str = ""
        self._active_name: str | None = None

    def _player_args(self) -> list[str]:
        with self._lock:
            name = self._active_name
        return ["-p", name] if name else []

    def _control(self, *args: str) -> None:
        _playerctl(*self._player_args(), *args)
        # Force a fresh state read on the next poll so the screen updates fast.
        with self._lock:
            self._last_fetch = 0.0

    def _fetch(self) -> None:
        try:
            proc = subprocess.run(
                ["playerctl", "-a", "metadata", "--format", _FORMAT],
                capture_output=True, text=True, timeout=PLAYERCTL_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            log.debug("playerctl metadata failed: %s", e)
            self._cache = dict(_EMPTY)
            self._art_url = ""
            return

        if proc.returncode != 0 or not proc.stdout.strip():
            self._cache = dict(_EMPTY)
            self._art_url = ""
            return

        players = []
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 7:
                continue
            name, status, title, artist, length_us, position_us, art_url = parts
            players.append({
                "name": name,
                "status": status.strip().lower(),
                "title": title,
                "artist": artist,
                "length_us": length_us,
                "position_us": position_us,
                "art_url": art_url,
            })

        if not players:
            self._cache = dict(_EMPTY)
            self._art_url = ""
            return

        chosen = None
        if self._preferred_player:
            for p in players:
                if p["name"] == self._preferred_player or p["name"].startswith(
                    self._preferred_player + "."
                ):
                    chosen = p
                    break
        # Sticky selection: keep showing/controlling the player we last chose
        # (even after it's paused from the screen) unless another one starts
        # playing. Otherwise a pause would make the screen jump to another
        # player and the next "play" would go to the wrong app.
        current = next((p for p in players if p["name"] == self._active_name), None)
        if chosen is None and current is not None and current["status"] == "playing":
            chosen = current
        if chosen is None:
            chosen = next((p for p in players if p["status"] == "playing"), None)
        if chosen is None:
            chosen = current or players[0]
        self._active_name = chosen["name"]

        duration_s = _safe_int(chosen["length_us"]) // 1_000_000 if chosen["length_us"] else 0
        progress_s = _safe_int(chosen["position_us"]) // 1_000_000 if chosen["position_us"] else 0
        # Confirmed on the device: state is an int, 1 = playing, 0 = paused.
        # (String "playing" and bool true are NOT understood.)
        state = 1 if chosen["status"] == "playing" else 0

        self._cache = {
            "title": chosen["title"] or "",
            "artist": chosen["artist"] or "",
            "progress": max(0, progress_s),
            "duration": max(0, duration_s),
            "state": state,
            "index": 0,
        }
        self._art_url = chosen["art_url"] or ""

    def get(self) -> dict:
        """Return the cached (or freshly fetched) music_info payload."""
        with self._lock:
            now = time.monotonic()
            if now - self._last_fetch >= self._min_refresh:
                self._fetch()
                self._last_fetch = now
            return dict(self._cache)

    def get_art_url(self) -> str:
        """Return the cached current track's artUrl (possibly empty)."""
        with self._lock:
            return self._art_url

    # -- control (fire-and-forget commands from the device) --------------

    def play(self) -> None:
        self._control("play")

    def pause(self) -> None:
        self._control("pause")

    def next_track(self) -> None:
        self._control("next")

    def previous_track(self) -> None:
        self._control("previous")

    def seek(self, seconds: int) -> None:
        self._control("position", str(seconds))


def _playerctl(*args: str, timeout: float = PLAYERCTL_TIMEOUT) -> bool:
    try:
        subprocess.run(["playerctl", *args], capture_output=True, timeout=timeout)
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("playerctl %s failed: %s", " ".join(args), e)
        return False


def play() -> None:
    _playerctl("play")


def pause() -> None:
    _playerctl("pause")


def next_track() -> None:
    _playerctl("next")


def previous_track() -> None:
    _playerctl("previous")


def seek(seconds: int) -> None:
    _playerctl("position", str(seconds))
