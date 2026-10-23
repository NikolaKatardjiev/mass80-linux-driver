"""Optional TOML configuration for mass80d.

Config file: ``~/.config/mass80d/config.toml`` (overridable via --config).
All settings are optional; missing/invalid file -> defaults.
"""
from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field

log = logging.getLogger("mass80d.config")

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/mass80d/config.toml")

VALID_NET_UNITS = ("KB/s", "B/s")


@dataclass
class Config:
    net_unit: str = "KB/s"
    preferred_player: str | None = None
    log_level: str = "INFO"
    key_overrides: dict[str, str] = field(default_factory=dict)
    brightness_enabled: bool = True
    brightness_buses: list[int] | None = None

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        """Load config from ``path`` (or the default location).

        Never raises: any problem reading/parsing the file results in
        defaults being used (with a warning logged).
        """
        cfg = cls()
        chosen = path or DEFAULT_CONFIG_PATH
        if not os.path.exists(chosen):
            return cfg
        try:
            with open(chosen, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:  # noqa: BLE001 - never crash on config
            log.warning("failed to parse config %s: %s", chosen, e)
            return cfg

        net_unit = data.get("net_unit", cfg.net_unit)
        if net_unit not in VALID_NET_UNITS:
            log.warning("invalid net_unit %r, keeping %s", net_unit, cfg.net_unit)
        else:
            cfg.net_unit = net_unit

        cfg.preferred_player = data.get("preferred_player", cfg.preferred_player)
        cfg.log_level = str(data.get("log_level", cfg.log_level)).upper()

        overrides = data.get("key_overrides", {})
        if isinstance(overrides, dict):
            cfg.key_overrides = {str(k): str(v) for k, v in overrides.items()}
        else:
            log.warning("key_overrides must be a table, ignoring")

        cfg.brightness_enabled = bool(data.get("brightness_enabled", cfg.brightness_enabled))

        buses = data.get("brightness_buses")
        if buses is not None:
            if isinstance(buses, list) and all(isinstance(b, int) for b in buses):
                cfg.brightness_buses = list(buses)
            else:
                log.warning("brightness_buses must be a list of integers, ignoring")

        return cfg
