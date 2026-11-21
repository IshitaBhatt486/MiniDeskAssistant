"""hardware_tests/hardware_test.py: the single file with every hardware test (20 Nov 2026)."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

import numpy as np

import deskbot  # noqa: F401  (puts run_prototype/ and hardware_tests/ on sys.path)
import hardware_test as hw
import robot_config
from deskbot.companion import cli


class TestHardwareTest(unittest.TestCase):
    def test_fallback_pins_match_robot_config(self):
        # copied to the Pi alone, the file uses FALLBACK_PINS: they must not drift from robot_config.py
        for key, value in hw.FALLBACK_PINS.items():
            self.assertEqual(value, getattr(robot_config, key), key)

    def test_uses_robot_config_when_present(self):
        self.assertEqual(hw.PIN_SOURCE, "robot_config.py")

    def test_cli_tools_pick_real_tests(self):
        for name, args in cli.TOOL_ARGS.items():
            self.assertEqual(cli.PY_TOOLS[name][0], "hardware_tests/hardware_test.py", name)
            self.assertIn(args[0], hw.TESTS, name)

    def test_unknown_test_exits(self):
        with self.assertRaises(SystemExit):
            hw.main(["bogus"])

    def test_aliases_resolve(self):
        for alias, name in hw.ALIASES.items():
            self.assertIn(name, hw.TESTS, alias)

    def test_missing_library_is_reported_not_raised(self):
        with mock.patch.dict(sys.modules, {"gpiozero": None}), redirect_stdout(io.StringIO()) as out:
            code = hw.main(["touch"])
        self.assertEqual(code, 1)
        self.assertIn("gpiozero", out.getvalue())

    def test_menu_quits(self):
        with mock.patch("builtins.input", side_effect=["9", "q"]), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(hw.main([]), 0)
        self.assertIn("Enter a number", out.getvalue())

    def test_render_sizes(self):
        img = np.zeros((48, 64, 3), np.uint8)
        text = hw.render(img, 16, True)
        rows = text.split("\n")
        self.assertTrue(all(len(r) == 16 for r in rows))
        self.assertIn("\x1b[38;2;0;0;0m", hw.render(img, 8, False))


if __name__ == "__main__":
    unittest.main()
