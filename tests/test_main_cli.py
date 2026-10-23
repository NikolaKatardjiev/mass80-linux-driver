"""CLI smoke tests: --help and --version must work without touching hardware."""
import subprocess
import sys
import unittest


class MainCliTest(unittest.TestCase):
    def test_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "mass80d", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("mass80d", result.stdout.lower())

    def test_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "mass80d", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("mass80d", (result.stdout + result.stderr).lower())


if __name__ == "__main__":
    unittest.main()
