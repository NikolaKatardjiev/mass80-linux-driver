"""send_key vocabulary mapping tests (docs/PROTOCOL.md)."""
import unittest

from mass80d.providers.keys import is_ignored_name, resolve_key_name


class ResolveKeyNameTest(unittest.TestCase):
    def test_observed_real_names(self):
        # Exactly the names seen on the wire in live captures.
        self.assertEqual(resolve_key_name("Vol +"), "KEY_VOLUMEUP")
        self.assertEqual(resolve_key_name("Vol -"), "KEY_VOLUMEDOWN")
        self.assertEqual(resolve_key_name("Pause"), "KEY_PAUSE")
        self.assertEqual(resolve_key_name("Delete"), "KEY_DELETE")
        self.assertEqual(resolve_key_name("Print"), "KEY_SYSRQ")
        self.assertEqual(resolve_key_name("Home"), "KEY_HOME")

    def test_full_vendor_vocabulary_names(self):
        cases = {
            "Print Screen": "KEY_SYSRQ",
            "Scroll Lock": "KEY_SCROLLLOCK",
            "Backspace": "KEY_BACKSPACE",
            "Insert": "KEY_INSERT",
            "Page Up": "KEY_PAGEUP",
            "Page Down": "KEY_PAGEDOWN",
            "Num Lock": "KEY_NUMLOCK",
            "Caps Lock": "KEY_CAPSLOCK",
            "Enter": "KEY_ENTER",
            "Num Enter": "KEY_KPENTER",
            "Left Shift": "KEY_LEFTSHIFT",
            "Right Shift": "KEY_RIGHTSHIFT",
            "Left Ctrl": "KEY_LEFTCTRL",
            "Right Ctrl": "KEY_RIGHTCTRL",
            "Left Win": "KEY_LEFTMETA",
            "Right Win": "KEY_RIGHTMETA",
            "Left Alt": "KEY_LEFTALT",
            "Right Alt": "KEY_RIGHTALT",
            "Space": "KEY_SPACE",
            "Menu": "KEY_MENU",
            "Left": "KEY_LEFT",
            "Down": "KEY_DOWN",
            "Right": "KEY_RIGHT",
            "Up": "KEY_UP",
            "Mute": "KEY_MUTE",
            "Play": "KEY_PLAYPAUSE",
            "Media Stop": "KEY_STOPCD",
            "Pervious": "KEY_PREVIOUSSONG",  # verbatim vendor typo
            "Previous": "KEY_PREVIOUSSONG",
            "Next": "KEY_NEXTSONG",
            "Rewind": "KEY_REWIND",
            "Fast Forward": "KEY_FASTFORWARD",
            "Select": "KEY_SELECT",
            "Eject": "KEY_EJECTCD",
            "Bright -": "KEY_BRIGHTNESSDOWN",
            "Bright +": "KEY_BRIGHTNESSUP",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(resolve_key_name(name), expected)

    def test_plain_letters_digits_fkeys_esc_tab(self):
        self.assertEqual(resolve_key_name("A"), "KEY_A")
        self.assertEqual(resolve_key_name("a"), "KEY_A")
        self.assertEqual(resolve_key_name("5"), "KEY_5")
        self.assertEqual(resolve_key_name("F1"), "KEY_F1")
        self.assertEqual(resolve_key_name("F24"), "KEY_F24")
        self.assertEqual(resolve_key_name("Esc"), "KEY_ESC")
        self.assertEqual(resolve_key_name("Tab"), "KEY_TAB")

    def test_unknown_name_returns_none(self):
        self.assertIsNone(resolve_key_name("Something Nonexistent"))

    def test_overrides_take_priority(self):
        self.assertEqual(
            resolve_key_name("Vol +", overrides={"Vol +": "KEY_F13"}), "KEY_F13"
        )
        self.assertEqual(
            resolve_key_name("Custom Name", overrides={"Custom Name": "KEY_F14"}),
            "KEY_F14",
        )


class IgnoredNameTest(unittest.TestCase):
    def test_qmk_layer_names_ignored(self):
        for name in ("MO(0)", "MO(9)", "TG(3)", "TT(1)", "OSL(2)", "TO(4)", "DF(5)"):
            with self.subTest(name=name):
                self.assertTrue(is_ignored_name(name))

    def test_rgb_lighting_names_ignored(self):
        for name in ("Effect -", "Effect +", "Effect Speed -", "Effect Speed +",
                     "Color Hue -", "Color Hue +", "Color Sat -", "Color Sat +"):
            with self.subTest(name=name):
                self.assertTrue(is_ignored_name(name))

    def test_fn_layer_names_ignored(self):
        self.assertTrue(is_ignored_name("Fn1 (Fn3)"))
        self.assertTrue(is_ignored_name("Space Fn1"))

    def test_nothing_and_pass_through_ignored(self):
        self.assertTrue(is_ignored_name("Nothing"))
        self.assertTrue(is_ignored_name("Pass_through"))

    def test_real_keys_not_ignored(self):
        self.assertFalse(is_ignored_name("Vol +"))
        self.assertFalse(is_ignored_name("Home"))
        self.assertFalse(is_ignored_name("A"))


if __name__ == "__main__":
    unittest.main()
