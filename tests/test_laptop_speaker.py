"""The laptop as the robot's speaker (21 Nov 2026): run_prototype/deskbot/assistant/laptop_speaker.py + Speaker routing."""

import os
import threading
import time
import unittest

import numpy as np

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant.laptop_speaker import LaptopSpeaker, wav_duration
from deskbot.assistant.settings import validate
from deskbot.assistant.voice import Speaker, write_wav

HALF_SECOND = write_wav(np.zeros(8000, dtype=np.float32), 16000)


class FakeTTS:
    name = "fake"

    def synth(self, text):
        return HALF_SECOND


class Settings(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


def make_speaker(output):
    sp = Speaker(Settings(speaker_output=output, voice_style="natural"))
    sp.tts, sp.engine, sp.error = FakeTTS(), "fake", None
    sp.played = []
    sp.player.play = lambda wav: sp.played.append(len(wav))
    return sp


def wait_for(fn, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.02)
    return False


class LaptopSpeakerQueueTest(unittest.TestCase):
    def test_duration_from_header(self):
        self.assertAlmostEqual(wav_duration(HALF_SECOND), 0.5, places=3)
        self.assertEqual(wav_duration(b"not a wav"), 0.0)

    def test_new_page_does_not_replay_old_clips(self):
        ls = LaptopSpeaker()
        ls.push(HALF_SECOND, "reply", "old")
        out = ls.wait_clips(-1, 5)
        self.assertEqual(out["clips"], [])
        self.assertEqual(out["latest"], 1)

    def test_long_poll_wakes_on_a_new_clip(self):
        ls = LaptopSpeaker()
        threading.Timer(0.2, lambda: ls.push(HALF_SECOND, "reply", "hi")).start()
        t0 = time.monotonic()
        out = ls.wait_clips(0, 5, "tab")
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual([c["text"] for c in out["clips"]], ["hi"])
        self.assertEqual(ls.clip(1), HALF_SECOND)
        self.assertEqual(ls.listeners(), 1)

    def test_long_poll_times_out_empty(self):
        out = LaptopSpeaker().wait_clips(0, 0.2)
        self.assertEqual(out["clips"], [])

    def test_interrupt_clears_and_wakes(self):
        ls = LaptopSpeaker()
        ls.push(HALF_SECOND)
        threading.Timer(0.2, ls.interrupt).start()
        out = ls.wait_clips(1, 5, interrupt_seen=0)
        self.assertEqual(out["interrupt"], 1)
        self.assertIsNone(ls.clip(1))

    def test_keeps_only_the_newest(self):
        ls = LaptopSpeaker(keep=5)
        for i in range(12):
            ls.push(HALF_SECOND, "chatter", str(i))
        self.assertEqual([c["text"] for c in ls.wait_clips(0, 0)["clips"]], ["7", "8", "9", "10", "11"])


class SpeakerRoutingTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("DESKBOT_SPEAKER", None)

    def check(self, output, laptop_clips, robot_plays):
        sp = make_speaker(output)
        try:
            sp.say("Hello there.", "reply")
            sp.chime("fanfare")
            self.assertTrue(wait_for(lambda: sp.spoken == 1 and sp._q.empty() and sp.speaking is None))
            time.sleep(1.5)       # the chime after the speech
            kinds = [c["kind"] for c in sp.laptop.wait_clips(0, 0)["clips"]]
            self.assertEqual(kinds, laptop_clips)
            self.assertEqual(len(sp.played), robot_plays)
            self.assertEqual(sp.status()["output"], output)
        finally:
            sp.close()

    def test_laptop(self):
        self.check("laptop", ["reply", "motif"], 0)

    def test_robot(self):
        self.check("robot", [], 2)

    def test_both(self):
        self.check("both", ["reply", "motif"], 2)

    def test_env_overrides_setting(self):
        os.environ["DESKBOT_SPEAKER"] = "robot"
        sp = make_speaker("laptop")
        self.assertEqual(sp.output(), "robot")
        sp.close()

    def test_stop_interrupts_the_laptop(self):
        sp = make_speaker("laptop")
        sp.interrupt()
        self.assertEqual(sp.laptop.interrupts, 1)
        sp.close()

    def test_setting_is_validated(self):
        self.assertEqual(validate({"speaker_output": "both"}), {"speaker_output": "both"})
        with self.assertRaises(ValueError):
            validate({"speaker_output": "loud"})


if __name__ == "__main__":
    unittest.main()
