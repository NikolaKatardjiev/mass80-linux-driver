"""mass80d entry point."""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

from . import __version__
from .config import Config
from .protocol import Dispatcher, build_time_payload
from .providers import cover as cover_mod
from .providers import keys as keys_mod
from .providers import misc as misc_mod
from .providers import perf as perf_mod
from .providers import volume as volume_mod
from .providers.brightness import BrightnessProvider
from .providers.caps import CapsProvider
from .providers.music import MusicProvider
from .transport import SerialTransport

log = logging.getLogger("mass80d")

CAPS_POLL_INTERVAL = 0.25


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="mass80d",
        description="Companion daemon for the Mass80 keyboard's touchscreen.",
    )
    ap.add_argument("--verbose", "-v", action="store_true", help="enable debug logging")
    ap.add_argument("--config", default=None, help="path to config.toml (default: ~/.config/mass80d/config.toml)")
    ap.add_argument("--log-raw", action="store_true", help="log every raw line read from the serial port")
    ap.add_argument("--version", action="version", version=f"mass80d {__version__}")
    return ap.parse_args(argv)


def _caps_watcher(caps: CapsProvider, transport: SerialTransport, stop: threading.Event) -> None:
    """Poll the Caps Lock LED and push an unsolicited get_time on change."""
    last = None
    while not stop.is_set():
        try:
            caps.refresh()
            state = caps.read()
        except Exception:  # noqa: BLE001
            state = False
        if last is not None and state != last:
            transport.send(build_time_payload(state))
        last = state
        stop.wait(CAPS_POLL_INTERVAL)


def main(argv=None) -> int:
    args = parse_args(argv)
    config = Config.load(args.config)

    level = logging.DEBUG if args.verbose else getattr(logging, config.log_level, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("PIL").setLevel(logging.WARNING)

    log.info("mass80d %s starting", __version__)

    caps = CapsProvider()
    music = MusicProvider(preferred_player=config.preferred_player)
    cover = cover_mod.CoverProvider()
    perf = perf_mod.PerformanceProvider(net_unit=config.net_unit)
    keys = keys_mod.KeyProvider(key_overrides=config.key_overrides)
    brightness = BrightnessProvider(
        enabled=config.brightness_enabled, buses=config.brightness_buses
    )

    dispatcher = Dispatcher(
        transport=None,
        music=music,
        cover=cover,
        perf=perf,
        caps=caps,
        keys=keys,
        volume_mod=volume_mod,
        misc_mod=misc_mod,
        brightness=brightness,
        config=config,
    )

    transport = SerialTransport(on_line=dispatcher.handle_line, log_raw=args.log_raw)
    dispatcher._transport = transport  # wire up now that both exist

    stop = threading.Event()
    watcher = threading.Thread(
        target=_caps_watcher, args=(caps, transport, stop), daemon=True, name="caps-watcher"
    )
    watcher.start()

    try:
        transport.run()
    except KeyboardInterrupt:
        log.info("interrupted, shutting down")
    finally:
        stop.set()
        transport.stop()
        keys.close()
        brightness.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
