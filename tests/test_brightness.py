"""BrightnessProvider tests: coalescing, clamping, bus parsing -- no real
ddcutil/hardware access, everything goes through a FakeRunner."""
import subprocess
import threading
import time
import unittest

from mass80d.providers.brightness import (
    BrightnessProvider,
    parse_detect_buses,
    parse_getvcp_value,
)

DETECT_BRIEF_SAMPLE = """\
Display 1
   I2C bus:          /dev/i2c-11
   DRM connector:    card1-HDMI-A-2
   drm_connector_id: 472
   Monitor:          MSI:MSI MAG322CQR:DA7A130110087

Display 2
   I2C bus:          /dev/i2c-14
   DRM connector:    card1-DP-2
   drm_connector_id: 458
   Monitor:          MSI:MSI MAG322CQR:DA7A020110003

"""

GETVCP_BRIEF_SAMPLE = "VCP 10 C 100 100\n"


def _result(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class ParsingTest(unittest.TestCase):
    def test_parse_detect_buses(self):
        self.assertEqual(parse_detect_buses(DETECT_BRIEF_SAMPLE), [11, 14])

    def test_parse_detect_buses_empty(self):
        self.assertEqual(parse_detect_buses("No displays found\n"), [])

    def test_parse_getvcp_value(self):
        self.assertEqual(parse_getvcp_value(GETVCP_BRIEF_SAMPLE), 100)

    def test_parse_getvcp_value_other_level(self):
        self.assertEqual(parse_getvcp_value("VCP 10 C 42 100\n"), 42)

    def test_parse_getvcp_value_malformed(self):
        self.assertIsNone(parse_getvcp_value("nonsense"))


class FakeRunner:
    """Records every invocation; lets tests script per-call behavior."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.lock = threading.Lock()
        self._detect_result = _result(0, DETECT_BRIEF_SAMPLE)
        self._setvcp_result = _result(0)
        self._getvcp_result = _result(0, GETVCP_BRIEF_SAMPLE)
        # optional artificial delay to simulate slow ddcutil calls
        self.delay = 0.0
        self.setvcp_results_by_bus: dict[int, subprocess.CompletedProcess] = {}

    def __call__(self, args, timeout=None):
        with self.lock:
            self.calls.append(list(args))
        if self.delay:
            time.sleep(self.delay)
        if "detect" in args:
            return self._detect_result
        if "getvcp" in args:
            return self._getvcp_result
        if "setvcp" in args:
            bus = int(args[args.index("--bus") + 1])
            return self.setvcp_results_by_bus.get(bus, self._setvcp_result)
        raise AssertionError(f"unexpected ddcutil invocation: {args}")

    def setvcp_calls(self):
        with self.lock:
            return [c for c in self.calls if "setvcp" in c]


def wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class SetTest(unittest.TestCase):
    def test_set_applies_to_all_detected_buses(self):
        runner = FakeRunner()
        provider = BrightnessProvider(runner=runner)
        try:
            provider.set(42)
            self.assertTrue(wait_until(lambda: len(runner.setvcp_calls()) >= 2))
            calls = runner.setvcp_calls()
            buses_called = {int(c[c.index("--bus") + 1]) for c in calls}
            self.assertEqual(buses_called, {11, 14})
            for c in calls:
                self.assertIn("42", c)
                self.assertIn("--noverify", c)
        finally:
            provider.stop()

    def test_value_is_clamped(self):
        runner = FakeRunner()
        provider = BrightnessProvider(runner=runner)
        try:
            provider.set(500)
            self.assertTrue(wait_until(lambda: len(runner.setvcp_calls()) >= 2))
            for c in runner.setvcp_calls():
                self.assertIn("100", c)

            runner.calls.clear()
            provider.set(-20)
            self.assertTrue(wait_until(lambda: len(runner.setvcp_calls()) >= 2))
            for c in runner.setvcp_calls():
                self.assertIn("0", c)
        finally:
            provider.stop()

    def test_disabled_provider_never_calls_ddcutil(self):
        runner = FakeRunner()
        provider = BrightnessProvider(enabled=False, runner=runner)
        try:
            provider.set(50)
            time.sleep(0.2)
            self.assertEqual(runner.calls, [])
        finally:
            provider.stop()

    def test_configured_buses_skip_detection(self):
        runner = FakeRunner()
        provider = BrightnessProvider(buses=[99], runner=runner)
        try:
            provider.set(10)
            self.assertTrue(wait_until(lambda: len(runner.setvcp_calls()) >= 1))
            self.assertFalse(any("detect" in c for c in runner.calls))
            buses_called = {int(c[c.index("--bus") + 1]) for c in runner.setvcp_calls()}
            self.assertEqual(buses_called, {99})
        finally:
            provider.stop()


class CoalescingTest(unittest.TestCase):
    def test_rapid_sets_apply_only_final_value(self):
        runner = FakeRunner()
        # Make each ddcutil call slow enough that a burst of set() calls
        # piles up while the worker is still busy with the first one.
        runner.delay = 0.1
        provider = BrightnessProvider(runner=runner)
        try:
            # First set() kicks off the worker applying value 1 (slow).
            provider.set(1)
            time.sleep(0.02)  # let the worker pick up value 1 and start sleeping
            # Flood with rapid updates like a slider drag at ~30Hz.
            for v in range(2, 30):
                provider.set(v)
            # Wait for the worker to finish applying the burst.
            self.assertTrue(wait_until(lambda: len(runner.setvcp_calls()) >= 4, timeout=5.0))
            time.sleep(0.3)  # ensure worker goes idle (no more pending values)

            calls = runner.setvcp_calls()
            applied_values = []
            for c in calls:
                # value is the 5th element: [ddcutil, --bus, N, setvcp, 10, VALUE, ...]
                idx = c.index("setvcp")
                applied_values.append(int(c[idx + 2]))

            # The very last applied value must be the final one requested (29).
            self.assertEqual(applied_values[-1], 29)
            # Coalescing means we should have applied far fewer than 29*2 calls.
            self.assertLess(len(calls), 29 * 2)
        finally:
            provider.stop()


class FailureHandlingTest(unittest.TestCase):
    def test_failed_setvcp_triggers_redetect_on_next_set(self):
        runner = FakeRunner()
        runner.setvcp_results_by_bus[11] = _result(1, stderr="DDC communication failed")
        provider = BrightnessProvider(runner=runner)
        try:
            provider.set(50)
            self.assertTrue(wait_until(lambda: len(runner.setvcp_calls()) >= 2))

            detect_calls_before = sum(1 for c in runner.calls if "detect" in c)
            self.assertEqual(detect_calls_before, 1)

            # Fix the simulated failure and set again; provider should
            # re-detect (bus list was invalidated after the failure).
            runner.setvcp_results_by_bus.clear()
            provider.set(60)
            self.assertTrue(
                wait_until(lambda: sum(1 for c in runner.calls if "detect" in c) >= 2)
            )
        finally:
            provider.stop()


class QueryTest(unittest.TestCase):
    def test_query_cached_returns_none_then_value_after_async_refresh(self):
        runner = FakeRunner()
        provider = BrightnessProvider(runner=runner)
        try:
            first = provider.query_cached()
            self.assertIsNone(first)
            self.assertTrue(wait_until(lambda: provider.query_cached() == 100))
        finally:
            provider.stop()

    def test_query_cached_reflects_last_set_value_without_extra_getvcp(self):
        runner = FakeRunner()
        provider = BrightnessProvider(runner=runner)
        try:
            provider.set(77)
            # Wait for the set() to actually be applied (both displays), via
            # the runner's own call log -- not by polling query_cached()
            # itself, which (like the real device asking a query right after
            # a slider drag) can race the apply and legitimately trigger one
            # background getvcp refresh before the value lands. Once the set
            # has landed, a *subsequent* query must be served from cache.
            self.assertTrue(wait_until(lambda: len(runner.setvcp_calls()) >= 2))
            self.assertEqual(provider.query_cached(), 77)

            getvcp_calls_so_far = sum(1 for c in runner.calls if "getvcp" in c)
            time.sleep(0.1)
            # No *new* getvcp calls should appear once the cache is backed by
            # an applied value.
            self.assertEqual(
                sum(1 for c in runner.calls if "getvcp" in c), getvcp_calls_so_far
            )
        finally:
            provider.stop()

    def test_disabled_provider_query_returns_none(self):
        runner = FakeRunner()
        provider = BrightnessProvider(enabled=False, runner=runner)
        try:
            self.assertIsNone(provider.query_cached())
            time.sleep(0.1)
            self.assertEqual(runner.calls, [])
        finally:
            provider.stop()


if __name__ == "__main__":
    unittest.main()
