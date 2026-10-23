# mass80d

Linux userspace companion daemon for the **Mass80** keyboard's touchscreen
module. It talks the reverse-engineered newline-delimited JSON protocol over
the screen controller's USB CDC-ACM port (`303a:4003`) and answers the
device's requests for the clock, Caps Lock state, now-playing music/album
art, and system performance, plus executes the device's remote-control
commands (media keys, volume, URL opening, `send_key` keystroke emulation,
...).

See [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the reverse-engineered wire
protocol this daemon implements.

## Features

- `get_time` — replies with local time + UTC offset + Caps Lock state; also
  pushes an unsolicited update within ~250ms of the Caps Lock LED changing.
- `get_music_info` / `get_cover(_prev/_next)` — sourced from MPRIS via
  `playerctl`; album art is fetched, center-cropped, resized, and
  re-encoded as JPEG.
- `get_performance` — CPU/RAM/frequency/temperature/network throughput via
  `psutil`.
- Playback control (`music_play/pause/next/prev/seek`) via `playerctl`.
- Volume control/query and mute via `wpctl` (PipeWire).
- `open_url` via `xdg-open` (http/https only).
- `send_key` — emulates the vendor vocabulary of key names (media keys,
  navigation, modifiers, F-keys, letters/digits, ...) through a virtual
  `python-evdev` `uinput` keyboard. QMK-layer and RGB/lighting meta-keys
  (`MO(n)`, `Effect +`, ...) are intentionally ignored (logged at info).
- `enter_udisk_mode` — releases the serial port and pauses reconnects for
  ~10s so the device can mount as USB mass storage without contention.
- Reconnects automatically across the device's USB re-enumeration (reboot,
  theme change, etc).

## Requirements

- Python 3.11+ (developed against 3.14).
- Python packages: `pyserial`, `psutil`, `evdev`, `Pillow` (see
  `pyproject.toml`).
- CLI tools on `PATH`: `playerctl`, `wpctl`, `xdg-open`.
- Read access to `/dev/ttyACM*` for the device and write access to
  `/dev/uinput` (for `send_key`). On most desktop distros these are granted
  via udev `uaccess`/ACLs to the active logind session; otherwise add your
  user to the relevant group (commonly `dialout`/`input`) or add a udev rule.

## Install

Dependencies (Arch/CachyOS): `python-pyserial python-psutil python-evdev
python-pillow playerctl ddcutil` (plus PipeWire's `wpctl`).

### Run as a systemd user service

```sh
./install.sh
```

This installs `~/.config/systemd/user/mass80d.service` pointing at this
checkout (via `PYTHONPATH`) and enables it under `graphical-session.target`.
After `git pull`, just `systemctl --user restart mass80d`.

Check status / logs:

```sh
systemctl --user status mass80d
journalctl --user -u mass80d -f
```

### Manual run (for debugging)

```sh
python3 -m mass80d --verbose
```

Useful flags:

- `--verbose` / `-v` — debug-level logging.
- `--config PATH` — use a config file other than the default location.
- `--log-raw` — log every raw line read from the serial port (noisy; useful
  for protocol debugging alongside `tools/probe.py`).

## Configuration

Optional TOML file at `~/.config/mass80d/config.toml` (all keys optional):

```toml
# Units for net_upload/net_download in get_performance. The real firmware's
# expected unit is unconfirmed; default matches the host app's likely
# behavior (see docs/PROTOCOL.md).
net_unit = "KB/s"  # or "B/s"

# Prefer a specific MPRIS player by name (e.g. "spotify", "firefox") when
# multiple players are active and none is currently "Playing".
preferred_player = "spotify"

log_level = "INFO"

# Override/extend the send_key vocabulary -> evdev KEY_* name mapping.
[key_overrides]
"Some Odd Name" = "KEY_F13"
```

## Troubleshooting

- **No reply from the daemon / device stuck**: confirm the daemon sees the
  device — `journalctl --user -u mass80d -f` should log `connected
  /dev/ttyACM*` shortly after plugging in or rebooting the keyboard. The
  device re-enumerates on reboot/theme change; the daemon reconnects
  automatically within ~0.5s of noticing the new node.
- **`send_key` does nothing**: check `/dev/uinput` is writable by your user
  (`ls -l /dev/uinput`), and that `python-evdev` is actually installed in
  the environment running the daemon (`python3 -c "import evdev"`).
- **No music/art shown**: `playerctl -l` and `playerctl metadata` should
  show your player; if nothing is "Playing", the daemon won't show anything
  either until a player's status is `Playing` (or set `preferred_player`).
- **Album art never updates**: art is fetched from the MPRIS `artUrl`
  (`file://` or `http(s)://`) and cached per-URL for ~30s; some players
  (notably browsers) may not expose `artUrl` at all.
- **Volume control not working**: confirm `wpctl --help`/`wpctl status`
  work standalone and that PipeWire (not plain PulseAudio) owns your audio
  sink.
- **Protocol questions / adding new actions**: start with
  `docs/PROTOCOL.md`, and `tools/probe.py` for a
  minimal standalone capture/reply tool useful for live experiments without
  running the full daemon.

## Development

```sh
python3 -m unittest discover -s tests -v
```

Do **not** run the daemon and `tools/probe.py` against the real device at
the same time — only one process can hold the serial port.
