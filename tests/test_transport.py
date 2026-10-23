"""Framing tests: partial/merged lines mixed with real firmware debug noise.

Noise samples lifted verbatim from live device captures (see
docs/PROTOCOL.md: firmware emits non-JSON
[CDC-TX]/[C0]/[C1] debug lines that are *not* sent as real RX on the wire in
our own captures -- those are the probe echoing its own logging -- but the
daemon's framing must tolerate equivalent noise appearing on the actual
serial stream regardless).
"""
import unittest

from mass80d.transport import LineSplitter, extract_json_candidate, is_json_line

NOISE_LINE_1 = (
    "[C0]lvgl-8pct,IDLE0-71pct,esp_timer-1pct,ipc0-0pct,, "
    "\u5185\u90e8RAM: \u5df2\u7528=383 KB, \u5269\u4f59=117 KB (\u6700\u5927\u5757=46 KB)"
)
NOISE_LINE_2 = (
    "[C1]mjpeg_ui-20pct,IDLE1-91pct,sys_monitor-0pct,usb_cdc_task-0pct,"
    "TinyUSB-0pct,swdraw-6pct,ipc1-0pct,"
)
REAL_JSON_LINE = '{"action":"get_time","version":"0.13.4"}'
REAL_MUSIC_LINE = '{"action":"get_music_info"}'


class LineSplitterTest(unittest.TestCase):
    def test_single_complete_line(self):
        splitter = LineSplitter()
        lines = splitter.feed((REAL_JSON_LINE + "\n").encode())
        self.assertEqual(lines, [REAL_JSON_LINE])

    def test_partial_line_split_across_feeds(self):
        splitter = LineSplitter()
        data = (REAL_JSON_LINE + "\n").encode()
        first, second = data[:10], data[10:]
        self.assertEqual(splitter.feed(first), [])
        self.assertEqual(splitter.feed(second), [REAL_JSON_LINE])

    def test_merged_lines_in_one_chunk(self):
        splitter = LineSplitter()
        chunk = (NOISE_LINE_1 + "\n" + REAL_JSON_LINE + "\n" + NOISE_LINE_2 + "\n").encode(
            "utf-8"
        )
        lines = splitter.feed(chunk)
        self.assertEqual(lines, [NOISE_LINE_1, REAL_JSON_LINE, NOISE_LINE_2])

    def test_debug_noise_glued_to_json_like_real_capture(self):
        # Reproduces the exact shape seen in a live capture:
        # a debug noise fragment immediately followed (same line) by a
        # parenthesized firmware echo of JSON it transmitted.
        glued = (
            "[C1]mjpeg_ui-20pct,IDLE1-91pct,sys_monitor-0pct,usb_cdc_task-0pct,"
            'TinyUSB-0pct,swdraw-6pct,ipc1-0pct,[CDC-TX] ("action":"get_time","version":"0.13.4")'
        )
        splitter = LineSplitter()
        lines = splitter.feed((glued + "\n").encode())
        self.assertEqual(lines, [glued])
        # This whole merged line uses parens, not braces -> not JSON-like.
        self.assertFalse(is_json_line(lines[0]))

    def test_empty_lines_are_dropped(self):
        splitter = LineSplitter()
        lines = splitter.feed(b"\n\n\n" + (REAL_JSON_LINE + "\n").encode())
        self.assertEqual(lines, [REAL_JSON_LINE])

    def test_byte_at_a_time_feed(self):
        splitter = LineSplitter()
        data = (REAL_JSON_LINE + "\n").encode()
        collected = []
        for b in data:
            collected.extend(splitter.feed(bytes([b])))
        self.assertEqual(collected, [REAL_JSON_LINE])


class JsonDetectionTest(unittest.TestCase):
    def test_real_json_line_detected(self):
        self.assertTrue(is_json_line(REAL_JSON_LINE))
        self.assertEqual(extract_json_candidate(REAL_JSON_LINE), REAL_JSON_LINE)

    def test_pure_noise_line_rejected(self):
        self.assertFalse(is_json_line(NOISE_LINE_1))
        self.assertIsNone(extract_json_candidate(NOISE_LINE_1))
        self.assertFalse(is_json_line(NOISE_LINE_2))

    def test_json_glued_after_noise_prefix_is_extracted(self):
        glued = NOISE_LINE_2 + REAL_MUSIC_LINE
        self.assertTrue(is_json_line(glued))
        self.assertEqual(extract_json_candidate(glued), REAL_MUSIC_LINE)


if __name__ == "__main__":
    unittest.main()
