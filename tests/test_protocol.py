"""Dispatch tests: exact reply JSON shapes against fake providers."""
import unittest

from mass80d.protocol import Dispatcher


class FakeTransport:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.paused_for = None

    def send(self, obj):
        self.sent.append(obj)

    def close(self):
        self.closed = True

    def pause_reconnect(self, seconds):
        self.paused_for = seconds


class FakeCaps:
    def __init__(self, state=False):
        self.state = state

    def read(self):
        return self.state


class FakeMusic:
    def __init__(self, info=None, art_url=""):
        self._info = info or {
            "title": "Song",
            "artist": "Artist",
            "progress": 12,
            "duration": 180,
            "state": 1,
            "index": 0,
        }
        self._art_url = art_url
        self.calls = []

    def get(self):
        return dict(self._info)

    def get_art_url(self):
        return self._art_url

    def play(self):
        self.calls.append("play")

    def pause(self):
        self.calls.append("pause")

    def next_track(self):
        self.calls.append("next")

    def previous_track(self):
        self.calls.append("previous")

    def seek(self, seconds):
        self.calls.append(("seek", seconds))


class FakePerf:
    def get(self):
        return {
            "cpu_usage": 42,
            "memory_usage": 55,
            "cpu_freq": 4200,
            "cpu_freq_full": 5000,
            "cpu_temp": 61,
            "net_upload": 100,
            "net_download": 2000,
        }


class FakeCover:
    def get_cover_b64(self, url, width, height):
        return "ZmFrZS1qcGVn"  # "fake-jpeg"


class FakeKeys:
    def __init__(self):
        self.sent = []

    def send(self, key):
        self.sent.append(key)


class FakeVolumeModule:
    def __init__(self, value=33, muted=False):
        self.value = value
        self.muted = muted
        self.set_calls = []
        self.toggle_calls = 0

    def get_volume(self):
        return self.value, self.muted

    def set_volume(self, value):
        self.set_calls.append(value)
        self.value = value

    def toggle_mute(self):
        self.toggle_calls += 1


class FakeMiscModule:
    def __init__(self):
        self.urls = []

    def open_url(self, value):
        self.urls.append(value)


def make_dispatcher(**overrides):
    transport = overrides.get("transport", FakeTransport())
    caps = overrides.get("caps", FakeCaps())
    music = overrides.get("music", FakeMusic())
    perf = overrides.get("perf", FakePerf())
    cover = overrides.get("cover", FakeCover())
    keys = overrides.get("keys", FakeKeys())
    volume_mod = overrides.get("volume_mod", FakeVolumeModule())
    misc_mod = overrides.get("misc_mod", FakeMiscModule())
    d = Dispatcher(
        transport=transport, music=music, cover=cover, perf=perf,
        caps=caps, keys=keys, volume_mod=volume_mod, misc_mod=misc_mod,
    )
    return d, transport, caps, music, perf, cover, keys, volume_mod, misc_mod


class GetTimeTest(unittest.TestCase):
    def test_shape_and_caps_false(self):
        d, transport, caps, *_ = make_dispatcher(caps=FakeCaps(False))
        reply = d.dispatch({"action": "get_time", "version": "0.13.4"})
        self.assertEqual(reply["action"], "get_time")
        self.assertIsInstance(reply["time"], str)
        # YYYY-MM-DD HH:MM:SS
        import re
        self.assertRegex(reply["time"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertIsInstance(reply["timezone"], int)
        self.assertIs(reply["caps"], False)
        self.assertEqual(transport.sent, [reply])

    def test_caps_true(self):
        d, transport, *_ = make_dispatcher(caps=FakeCaps(True))
        reply = d.dispatch({"action": "get_time"})
        self.assertIs(reply["caps"], True)


class GetMusicInfoTest(unittest.TestCase):
    def test_exact_shape(self):
        d, transport, *_ = make_dispatcher()
        reply = d.dispatch({"action": "get_music_info"})
        self.assertEqual(reply, {
            "action": "get_music_info",
            "title": "Song",
            "artist": "Artist",
            "progress": 12,
            "duration": 180,
            "state": 1,
            "index": 0,
        })

    def test_idle_defaults_when_provider_missing(self):
        d = Dispatcher(transport=FakeTransport())  # no music provider at all
        reply = d.dispatch({"action": "get_music_info"})
        self.assertEqual(reply, {
            "action": "get_music_info",
            "title": "",
            "artist": "",
            "progress": 0,
            "duration": 0,
            "state": 0,
            "index": 0,
        })

    def test_provider_exception_falls_back_safely(self):
        class ExplodingMusic:
            def get(self):
                raise RuntimeError("boom")

        d, *_ = make_dispatcher(music=ExplodingMusic())
        reply = d.dispatch({"action": "get_music_info"})
        self.assertEqual(reply["state"], 0)
        self.assertEqual(reply["title"], "")


class GetPerformanceTest(unittest.TestCase):
    def test_exact_shape(self):
        d, *_ = make_dispatcher()
        reply = d.dispatch({"action": "get_performance"})
        self.assertEqual(reply, {
            "action": "get_performance",
            "cpu_usage": 42,
            "memory_usage": 55,
            "cpu_freq": 4200,
            "cpu_freq_full": 5000,
            "cpu_temp": 61,
            "net_upload": 100,
            "net_download": 2000,
        })


class GetCoverTest(unittest.TestCase):
    def test_echoes_action_and_index(self):
        d, *_ = make_dispatcher()
        for action in ("get_cover", "get_cover_prev", "get_cover_next"):
            reply = d.dispatch({"action": action, "width": 480, "height": 480, "index": 3})
            self.assertEqual(reply["action"], action)
            self.assertEqual(reply["index"], 3)
            self.assertEqual(reply["image_data"], "ZmFrZS1qcGVn")


class CommandsNoReplyTest(unittest.TestCase):
    def test_music_transport_commands(self):
        music = FakeMusic()
        d, transport, *_ = make_dispatcher(music=music)
        self.assertIsNone(d.dispatch({"action": "music_play"}))
        self.assertIsNone(d.dispatch({"action": "music_pause"}))
        self.assertIsNone(d.dispatch({"action": "music_next"}))
        self.assertIsNone(d.dispatch({"action": "music_prev"}))
        self.assertIsNone(d.dispatch({"action": "music_seek", "time": 42}))
        self.assertEqual(music.calls, ["play", "pause", "next", "previous", ("seek", 42)])
        self.assertEqual(transport.sent, [])

    def test_send_key_dispatches_to_keys_provider(self):
        keys = FakeKeys()
        d, *_ = make_dispatcher(keys=keys)
        d.dispatch({"action": "send_key", "key": "Vol +"})
        self.assertEqual(keys.sent, ["Vol +"])

    def test_open_url_dispatches_to_misc(self):
        misc = FakeMiscModule()
        d, *_ = make_dispatcher(misc_mod=misc)
        d.dispatch({"action": "open_url", "value": "example.com"})
        self.assertEqual(misc.urls, ["example.com"])


class VolumeTest(unittest.TestCase):
    def test_set_volume_no_reply(self):
        vol_mod = FakeVolumeModule()
        d, transport, *_ = make_dispatcher(volume_mod=vol_mod)
        reply = d.dispatch({"action": "volume", "value": 77})
        self.assertIsNone(reply)
        self.assertEqual(vol_mod.set_calls, [77])
        self.assertEqual(transport.sent, [])

    def test_bare_volume_query_replies(self):
        vol_mod = FakeVolumeModule(value=33, muted=True)
        d, transport, *_ = make_dispatcher(volume_mod=vol_mod)
        reply = d.dispatch({"action": "volume"})
        self.assertEqual(reply, {"action": "volume", "value": 33, "muted": True})
        self.assertEqual(transport.sent, [reply])

    def test_query_action_replies_same_shape(self):
        vol_mod = FakeVolumeModule(value=10, muted=False)
        d, *_ = make_dispatcher(volume_mod=vol_mod)
        reply = d.dispatch({"action": "query"})
        self.assertEqual(reply, {"action": "volume", "value": 10, "muted": False})

    def test_mute_toggle(self):
        vol_mod = FakeVolumeModule()
        d, *_ = make_dispatcher(volume_mod=vol_mod)
        self.assertIsNone(d.dispatch({"action": "mute"}))
        self.assertIsNone(d.dispatch({"action": "toggle_mute"}))
        self.assertEqual(vol_mod.toggle_calls, 2)


class UdiskModeTest(unittest.TestCase):
    def test_closes_port_and_pauses_reconnect(self):
        transport = FakeTransport()
        d, *_ = make_dispatcher(transport=transport)
        d.dispatch({"action": "enter_udisk_mode"})
        self.assertTrue(transport.closed)
        self.assertEqual(transport.paused_for, 10.0)


class LogOnlyActionsTest(unittest.TestCase):
    def test_log_only_actions_never_reply_or_crash(self):
        d, transport, *_ = make_dispatcher()
        for action in ("light", "change_theme", "boot_diag", "boot_report", "cat_clap", "login"):
            reply = d.dispatch({"action": action, "value": 1})
            self.assertIsNone(reply)
        self.assertEqual(transport.sent, [])


class UnknownActionTest(unittest.TestCase):
    def test_unknown_action_returns_none_and_does_not_crash(self):
        d, transport, *_ = make_dispatcher()
        reply = d.dispatch({"action": "some_future_action", "value": 1})
        self.assertIsNone(reply)
        self.assertEqual(transport.sent, [])

    def test_missing_action_key_handled(self):
        d, *_ = make_dispatcher()
        self.assertIsNone(d.dispatch({"not_action": 1}))

    def test_bad_handler_never_crashes_dispatcher(self):
        class ExplodingKeys:
            def send(self, key):
                raise RuntimeError("boom")

        d, transport, *_ = make_dispatcher(keys=ExplodingKeys())
        reply = d.dispatch({"action": "send_key", "key": "Vol +"})
        self.assertIsNone(reply)  # must not propagate the exception


class HandleLineTest(unittest.TestCase):
    def test_malformed_json_is_ignored(self):
        d, transport, *_ = make_dispatcher()
        d.handle_line("{not valid json")
        self.assertEqual(transport.sent, [])

    def test_non_object_json_is_ignored(self):
        d, transport, *_ = make_dispatcher()
        d.handle_line("[1, 2, 3]")
        self.assertEqual(transport.sent, [])

    def test_valid_line_dispatches_and_sends(self):
        d, transport, *_ = make_dispatcher()
        d.handle_line('{"action":"get_music_info"}')
        self.assertEqual(len(transport.sent), 1)
        self.assertEqual(transport.sent[0]["action"], "get_music_info")


if __name__ == "__main__":
    unittest.main()
