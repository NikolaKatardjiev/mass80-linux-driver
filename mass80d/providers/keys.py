"""send_key handling: maps the vendor vocabulary to a virtual evdev keyboard.

Vocabulary source: docs/PROTOCOL.md (exact strings from the
vendor host app's key lookup table). Names not in the map (QMK layer
switches like ``MO(1)``, RGB/lighting meta-keys like ``Effect -``) are logged
at info level and ignored -- they have no meaningful Linux keyboard-event
equivalent and are presumably handled by the keyboard's own QMK firmware
directly, not by this daemon.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("mass80d.keys")

try:
    from evdev import UInput, ecodes
except Exception:  # noqa: BLE001 - evdev / /dev/uinput may be unavailable
    UInput = None  # type: ignore[assignment]
    ecodes = None  # type: ignore[assignment]

# Exact vendor vocabulary -> evdev KEY_* name.
KEY_MAP: dict[str, str] = {
    # Printing/locks/editing
    "Print Screen": "KEY_SYSRQ",
    "Print": "KEY_SYSRQ",
    "Scroll Lock": "KEY_SCROLLLOCK",
    "Pause": "KEY_PAUSE",
    "Backspace": "KEY_BACKSPACE",
    "Insert": "KEY_INSERT",
    "Delete": "KEY_DELETE",
    "Home": "KEY_HOME",
    "End": "KEY_END",
    "Page Up": "KEY_PAGEUP",
    "Page Down": "KEY_PAGEDOWN",
    "Num Lock": "KEY_NUMLOCK",
    "Caps Lock": "KEY_CAPSLOCK",
    "Enter": "KEY_ENTER",
    "Num Enter": "KEY_KPENTER",
    # Modifiers
    "Left Shift": "KEY_LEFTSHIFT",
    "Right Shift": "KEY_RIGHTSHIFT",
    "Left Ctrl": "KEY_LEFTCTRL",
    "Right Ctrl": "KEY_RIGHTCTRL",
    "Left Win": "KEY_LEFTMETA",
    "Right Win": "KEY_RIGHTMETA",
    "Left Alt": "KEY_LEFTALT",
    "Right Alt": "KEY_RIGHTALT",
    # Misc
    "Space": "KEY_SPACE",
    "Menu": "KEY_MENU",
    # Arrows
    "Left": "KEY_LEFT",
    "Down": "KEY_DOWN",
    "Right": "KEY_RIGHT",
    "Up": "KEY_UP",
    # Media
    "Vol -": "KEY_VOLUMEDOWN",
    "Vol +": "KEY_VOLUMEUP",
    "Mute": "KEY_MUTE",
    "Play": "KEY_PLAYPAUSE",
    "Media Stop": "KEY_STOPCD",
    "Pervious": "KEY_PREVIOUSSONG",  # sic: verbatim vendor typo
    "Previous": "KEY_PREVIOUSSONG",
    "Next": "KEY_NEXTSONG",
    "Rewind": "KEY_REWIND",
    "Fast Forward": "KEY_FASTFORWARD",
    "Select": "KEY_SELECT",
    "Eject": "KEY_EJECTCD",
    # Backlight
    "Bright -": "KEY_BRIGHTNESSDOWN",
    "Bright +": "KEY_BRIGHTNESSUP",
}

# Names known to be QMK-layer or RGB/lighting meta-actions with no sane
# evdev equivalent -- logged at info and ignored, not treated as "unknown".
_IGNORED_PATTERNS = (
    re.compile(r"^(MO|TG|TT|OSL|TO|DF)\(\d+\)$"),
    re.compile(r"^Fn\d+(\s*\(Fn\d+\))?$"),
    re.compile(r"^Space Fn\d+$"),
    re.compile(r"^Effect( Speed)? [+-]$"),
    re.compile(r"^Color (Hue|Sat) [+-]$"),
)

_IGNORED_LITERALS = {"Nothing", "Pass_through"}


def _extra_single_char_map() -> dict[str, str]:
    """Plain letters/digits -> KEY_<X>, built lazily from evdev ecodes."""
    out: dict[str, str] = {}
    for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        out[c] = f"KEY_{c}"
        out[c.lower()] = f"KEY_{c}"
    for d in "0123456789":
        out[d] = f"KEY_{d}"
    for i in range(1, 25):
        out[f"F{i}"] = f"KEY_F{i}"
    out["Esc"] = "KEY_ESC"
    out["Tab"] = "KEY_TAB"
    return out


_FALLBACK_NAMES = _extra_single_char_map()

_warned_unknown: set[str] = set()


def resolve_key_name(key: str, overrides: dict[str, str] | None = None) -> str | None:
    """Resolve a vendor key name to an evdev ``KEY_*`` name, or None."""
    if overrides and key in overrides:
        return overrides[key]
    if key in KEY_MAP:
        return KEY_MAP[key]
    if key in _FALLBACK_NAMES:
        return _FALLBACK_NAMES[key]
    return None


def is_ignored_name(key: str) -> bool:
    if key in _IGNORED_LITERALS:
        return True
    return any(p.match(key) for p in _IGNORED_PATTERNS)


class KeyProvider:
    """Lazily-created virtual keyboard for send_key emulation."""

    def __init__(self, key_overrides: dict[str, str] | None = None):
        self._overrides = key_overrides or {}
        self._uinput = None

    def _ensure_device(self):
        if self._uinput is not None:
            return self._uinput
        if UInput is None:
            log.warning("python-evdev unavailable; cannot emulate send_key")
            return None
        try:
            all_codes = set(KEY_MAP.values()) | set(_FALLBACK_NAMES.values())
            keys = [getattr(ecodes, name) for name in all_codes if hasattr(ecodes, name)]
            self._uinput = UInput({ecodes.EV_KEY: keys}, name="mass80d-virtual-kbd")
        except Exception as e:  # noqa: BLE001 - /dev/uinput permissions etc.
            log.warning("failed to create virtual keyboard: %s", e)
            self._uinput = None
        return self._uinput

    def send(self, key: str) -> None:
        if not key:
            return
        if is_ignored_name(key):
            log.info("ignoring QMK/lighting meta key: %r", key)
            return

        code_name = resolve_key_name(key, self._overrides)
        if code_name is None:
            if key not in _warned_unknown:
                _warned_unknown.add(key)
                log.warning("unknown send_key name: %r", key)
            return

        device = self._ensure_device()
        if device is None:
            return
        code = getattr(ecodes, code_name, None)
        if code is None:
            log.warning("mapped key %r -> %s has no evdev code", key, code_name)
            return
        try:
            device.write(ecodes.EV_KEY, code, 1)
            device.syn()
            device.write(ecodes.EV_KEY, code, 0)
            device.syn()
        except Exception as e:  # noqa: BLE001
            log.warning("failed to emit key %r: %s", key, e)

    def close(self) -> None:
        if self._uinput is not None:
            try:
                self._uinput.close()
            except Exception:  # noqa: BLE001
                pass
            self._uinput = None
