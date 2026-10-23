# Mass80 screen protocol (reverse-engineered)

## Transport
- Screen controller: Espressif chip behind the keyboard's internal hub (`1a40:0101`),
  USB `303a:4003` (briefly `303a:1001` JTAG/serial during boot), CDC-ACM → `/dev/ttyACM*`.
- Keyboard itself: `4d57:0080` (QMK/VIA, unrelated to the screen protocol).
- Newline-delimited JSON both directions. Port must be raw / no echo
  (a cooked tty echoes device output back into it).
- Firmware also emits debug lines (`[CDC-TX] ...`, `[CDC-RX] ...`, `[C0]...`) that are not JSON — ignore.
- Device queues outgoing messages while no host reads the port; they flush on open.
- Device re-enumerates on reboot/theme change → host must reconnect.
- Firmware version seen: `0.13.4`.

## Device → host requests (host replies with same `action`)
| action | request extras | reply fields | status |
|---|---|---|---|
| `get_time` | `version` | `time: "YYYY-MM-DD HH:MM:SS"`, `timezone` (minutes, guess) | sent; display unverified |
| `get_music_info` | — | `title`, `artist`, `progress` (s), `duration` (s), `state` (**int**: `1`=playing, `0`=paused) | **confirmed displays** |
| `get_performance` | — | `cpu_usage` %, `memory_usage` %, `cpu_freq` MHz, `cpu_freq_full` MHz, `cpu_temp` °C, `net_upload`, `net_download` | **confirmed displays** |
| `get_cover` / `get_cover_prev` / `get_cover_next` | `width:480,height:480,index` | `image_data` (base64) | format TBD |
| `boot_diag` | reboot diagnostics | none needed | — |

Firmware also parses `index`, `result`, `value`, `caps`, `new_version{version}`,
`cat_clap` / `keyboard_cat_clap` (semantics TBD).

## Device → host commands (host performs an action)
- `music_play`, `music_pause`, `music_next`, `music_prev`, `music_seek{time}`
- `volume{value}` (set volume; `{"action":"volume"}` without value likely a query)
- `light{value}` (brightness)
- `change_theme{id}` (1–5)
- `open_url{value}`
- `send_key{key}` — observed keys: `Vol +`, `Vol -`, `Pause`, `Delete`, `Print`, `Home`.
  Full vocabulary used by the vendor app: `Print Screen`, `Scroll Lock`, `Pause`,
  `Backspace`, `Insert`, `Delete`, `Home`, `Page Up`, `Page Down`, `Num Lock`,
  `Caps Lock`, `Enter`, `Num Enter`, `Left/Right Shift|Ctrl|Win|Alt`, `Space`,
  `Menu`, arrows, `Vol -`, `Vol +`, `Mute`, `Play`, `Media Stop`, `Pervious` (sic),
  `Next`, `Rewind`, `Fast Forward`, `Select`, `Eject`, `Bright -/+`, plus QMK/RGB
  meta-keys (`MO(n)`, `TG(n)`, `TT(n)`, `OSL(n)`, `TO(n)`, `DF(n)`, `Fn…`,
  `Effect ±`, `Effect Speed ±`, `Color Hue ±`, `Color Sat ±`).

## Implementation notes (`mass80d`)

The `mass80d/` package implements this protocol as a userspace daemon. A few
behaviors confirmed/decided during that implementation, not purely from
capture analysis:

- `get_time` reply additionally includes `caps` (bool, Caps Lock LED state)
  bundled in the same message, as the vendor host app does — i.e. the host doesn't need a separate
  message type for caps sync, it rides along on every `get_time` reply
  (both the polled one and an unsolicited push on LED state change).
- The device polls `get_time` roughly every 2s as a heartbeat; the daemon
  just answers every request rather than trying to detect/dedupe it.
- `get_cover`/`get_cover_prev`/`get_cover_next` replies use JPEG
  (quality 85, baseline/non-progressive), base64-encoded — this was not
  recoverable from static analysis and should be verified against the
  real device's rendering; the daemon keeps quality adjustable since the
  128KB device RX buffer caps the encoded line length.
- `net_upload`/`net_download` units are genuinely unconfirmed upstream; the
  daemon defaults to integer KB/s and exposes a `net_unit = "B/s"` config
  override — verify against real device throughput, like the vendor host
  app finding recommends.
- See `mass80d/providers/keys.py` for the full `send_key` vocabulary
  mapping (letters/digits/F1–F24 added defensively even though not observed
  on the wire) and which vendor key names are intentionally ignored
  (QMK layer switches, RGB/lighting meta-keys).
