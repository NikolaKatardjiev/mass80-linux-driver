"""Action dispatch: turns one parsed device JSON message into a reply (or
None) and/or a side effect (volume change, keypress, etc).

Every handler is wrapped so a single bad/unexpected message can never crash
the daemon or the reconnect loop; failures just log and fall back to safe
defaults.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, Optional

log = logging.getLogger("mass80d.protocol")

# Actions that are intentionally log-only (no reply, no real side effect we
# implement yet). Kept distinct from "unknown" so they don't warn every time.
# High-frequency polls; not logged per message.
_POLL_ACTIONS = {"get_time", "get_music_info", "get_performance",
                 "get_cover", "get_cover_prev", "get_cover_next",
                 "light_computer"}

_LOG_ONLY_ACTIONS = {"light", "change_theme", "boot_diag", "boot_report", "cat_clap", "login"}


def build_time_payload(caps: bool) -> dict:
    now = time.localtime()
    offset_seconds = -time.timezone if not now.tm_isdst else -time.altzone
    return {
        "action": "get_time",
        "time": time.strftime("%Y-%m-%d %H:%M:%S", now),
        "timezone": offset_seconds // 60,
        "caps": bool(caps),
    }


class Dispatcher:
    """Wires device JSON actions to providers. All providers are injected so
    tests can supply fakes."""

    def __init__(self, *, transport=None, music=None, cover=None, perf=None,
                 caps=None, keys=None, volume_mod=None, misc_mod=None,
                 brightness=None, config=None):
        self._transport = transport
        self._music = music
        self._cover = cover
        self._perf = perf
        self._caps = caps
        self._keys = keys
        self._volume = volume_mod
        self._misc = misc_mod
        self._brightness = brightness
        self._config = config
        self._warned_actions: set[str] = set()

        self._handlers: dict[str, Callable[[dict], Optional[dict]]] = {
            "get_time": self._h_get_time,
            "get_music_info": self._h_get_music_info,
            "get_performance": self._h_get_performance,
            "get_cover": self._h_get_cover,
            "get_cover_prev": self._h_get_cover,
            "get_cover_next": self._h_get_cover,
            "music_play": self._h_music_play,
            "music_pause": self._h_music_pause,
            "music_next": self._h_music_next,
            "music_prev": self._h_music_prev,
            "music_seek": self._h_music_seek,
            "volume": self._h_volume,
            "query": self._h_volume,
            "mute": self._h_mute,
            "toggle_mute": self._h_mute,
            "open_url": self._h_open_url,
            "send_key": self._h_send_key,
            "light_computer": self._h_light_computer,
            "enter_udisk_mode": self._h_enter_udisk_mode,
        }
        for action in _LOG_ONLY_ACTIONS:
            self._handlers[action] = self._make_log_only(action)

    # -- line/message entry points -----------------------------------------

    def handle_line(self, text: str) -> None:
        """Parse one JSON line and dispatch it; never raises."""
        try:
            msg = json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            log.debug("ignoring non-JSON/malformed line: %r (%s)", text, e)
            return
        if not isinstance(msg, dict):
            log.debug("ignoring non-object JSON line: %r", text)
            return
        self.dispatch(msg)

    def dispatch(self, msg: dict) -> Optional[dict]:
        action = msg.get("action")
        if not isinstance(action, str):
            log.debug("message with no/invalid action: %r", msg)
            return None

        if action not in _POLL_ACTIONS:
            log.info("RX %s", json.dumps(msg, ensure_ascii=False)[:300])

        handler = self._handlers.get(action)
        if handler is None:
            if action not in self._warned_actions:
                self._warned_actions.add(action)
                log.warning("unknown action: %r", action)
            return None

        try:
            reply = handler(msg)
        except Exception:  # noqa: BLE001 - a single bad message must never crash us
            log.exception("handler for action %r raised", action)
            return None

        if reply is not None and self._transport is not None:
            self._transport.send(reply)
        return reply

    # -- handlers -------------------------------------------------------

    def _h_get_time(self, msg: dict) -> dict:
        caps = False
        if self._caps is not None:
            try:
                caps = self._caps.read()
            except Exception:  # noqa: BLE001
                caps = False
        return build_time_payload(caps)

    def _h_get_music_info(self, msg: dict) -> dict:
        info = {
            "title": "",
            "artist": "",
            "progress": 0,
            "duration": 0,
            "state": 0,
            "index": 0,
        }
        if self._music is not None:
            try:
                fetched = self._music.get()
                info.update(fetched)
            except Exception:  # noqa: BLE001
                log.exception("music provider failed")
        info["action"] = "get_music_info"
        return info

    def _h_get_performance(self, msg: dict) -> dict:
        info = {
            "cpu_usage": 0,
            "memory_usage": 0,
            "cpu_freq": 0,
            "cpu_freq_full": 0,
            "cpu_temp": 0,
            "net_upload": 0,
            "net_download": 0,
        }
        if self._perf is not None:
            try:
                info.update(self._perf.get())
            except Exception:  # noqa: BLE001
                log.exception("performance provider failed")
        info["action"] = "get_performance"
        return info

    def _h_get_cover(self, msg: dict) -> dict:
        action = msg.get("action", "get_cover")
        width = msg.get("width", 480)
        height = msg.get("height", 480)
        index = msg.get("index", 0)
        image_data = ""
        if self._cover is not None:
            url = ""
            if self._music is not None:
                try:
                    url = self._music.get_art_url()
                except Exception:  # noqa: BLE001
                    url = ""
            try:
                image_data = self._cover.get_cover_b64(url, int(width), int(height))
            except Exception:  # noqa: BLE001
                log.exception("cover provider failed")
        return {
            "action": action,
            "index": index,
            "image_data": image_data,
        }

    def _h_music_play(self, msg: dict) -> None:
        if self._music is not None:
            self._music.play()

    def _h_music_pause(self, msg: dict) -> None:
        if self._music is not None:
            self._music.pause()

    def _h_music_next(self, msg: dict) -> None:
        if self._music is not None:
            self._music.next_track()

    def _h_music_prev(self, msg: dict) -> None:
        if self._music is not None:
            self._music.previous_track()

    def _h_music_seek(self, msg: dict) -> None:
        if self._music is None:
            return
        try:
            seconds = int(msg.get("time", 0))
        except (TypeError, ValueError):
            seconds = 0
        self._music.seek(seconds)

    def _h_volume(self, msg: dict) -> Optional[dict]:
        if self._volume is None:
            return None
        value = msg.get("value")
        if value is not None:
            try:
                self._volume.set_volume(int(value))
            except (TypeError, ValueError):
                log.warning("invalid volume value: %r", value)
            return None
        # Query (bare {"action":"volume"} or {"action":"query"}).
        try:
            vol, muted = self._volume.get_volume()
        except Exception:  # noqa: BLE001
            vol, muted = 0, False
        return {"action": "volume", "value": vol, "muted": muted}

    def _h_mute(self, msg: dict) -> None:
        if self._volume is not None:
            self._volume.toggle_mute()

    def _h_open_url(self, msg: dict) -> None:
        if self._misc is not None:
            self._misc.open_url(msg.get("value", ""))

    def _h_send_key(self, msg: dict) -> None:
        if self._keys is not None:
            self._keys.send(msg.get("key", ""))

    def _h_light_computer(self, msg: dict) -> Optional[dict]:
        """PC Light slider on the Home page: monitor brightness via DDC/CI.

        Sent at up to ~30Hz while dragging -- ``self._brightness.set()`` must
        be (and is) non-blocking so this never stalls the serial read loop.
        A bare/valueless message is treated as a query, replying with the
        last known (cached) brightness if available.
        """
        if self._brightness is None:
            return None
        value = msg.get("value")
        if value is not None:
            try:
                self._brightness.set(int(value))
            except (TypeError, ValueError):
                log.warning("invalid light_computer value: %r", value)
            return None
        cached = self._brightness.query_cached()
        if cached is None:
            return None
        return {"action": "light_computer", "value": cached}

    def _h_enter_udisk_mode(self, msg: dict) -> None:
        log.info("enter_udisk_mode: releasing serial, pausing reconnect ~10s")
        if self._transport is not None:
            self._transport.pause_reconnect(10.0)
            self._transport.close()

    def _make_log_only(self, action: str) -> Callable[[dict], None]:
        def _handler(msg: dict) -> None:
            log.info("%s: %r", action, msg)
        return _handler
