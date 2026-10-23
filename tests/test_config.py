"""Config loading tests."""
import os
import tempfile
import unittest

from mass80d.config import Config


class ConfigTest(unittest.TestCase):
    def test_missing_file_uses_defaults(self):
        cfg = Config.load("/nonexistent/path/config.toml")
        self.assertEqual(cfg.net_unit, "KB/s")
        self.assertIsNone(cfg.preferred_player)
        self.assertEqual(cfg.log_level, "INFO")
        self.assertEqual(cfg.key_overrides, {})

    def test_valid_file_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            with open(path, "w") as f:
                f.write(
                    'net_unit = "B/s"\n'
                    'preferred_player = "spotify"\n'
                    'log_level = "debug"\n'
                    "[key_overrides]\n"
                    '"Weird Key" = "KEY_F13"\n'
                )
            cfg = Config.load(path)
        self.assertEqual(cfg.net_unit, "B/s")
        self.assertEqual(cfg.preferred_player, "spotify")
        self.assertEqual(cfg.log_level, "DEBUG")
        self.assertEqual(cfg.key_overrides, {"Weird Key": "KEY_F13"})

    def test_invalid_net_unit_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            with open(path, "w") as f:
                f.write('net_unit = "Mbps"\n')
            cfg = Config.load(path)
        self.assertEqual(cfg.net_unit, "KB/s")

    def test_malformed_toml_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            with open(path, "w") as f:
                f.write("this is not valid toml {{{")
            cfg = Config.load(path)
        self.assertEqual(cfg.net_unit, "KB/s")


if __name__ == "__main__":
    unittest.main()
