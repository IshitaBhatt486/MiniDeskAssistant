"""
Rock, paper, scissors: best of three, played with your hand (camera gestures) or by voice.

    "let's play rock paper scissors"  -> "Rock... paper... scissors... shoot!"
    show:  fist = rock, open palm = paper, peace sign (Victory) = scissors   (MediaPipe gestures, companion/gestures.py)
    or say "rock" / "paper" / "scissors"

How a round works: the robot says the count-down; when the speaker has finished, it looks for a hand gesture for
REACT_S (2 s) and takes the first one it is sure of (or a spoken move from that moment on). It then says its own
move and who won, with a sound (ta-da / sad trombone / boing for a draw) and the eyes. No move seen: it asks once
more, then gives up. While a game is on, the gesture controller's normal actions are paused, so a fist doesn't
also stop the robot.

The robot's choice: random, but a little cheeky: half the time it plays what beats your most frequent move so
far (people repeat themselves). First to two wins; winning the match earns a celebration (you) or a dance (it).
"""

from __future__ import annotations

import random
import re
import threading
import time
from collections import Counter

MOVES = ("rock", "paper", "scissors")
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
GESTURE_MOVE = {"Closed_Fist": "rock", "Open_Palm": "paper", "Victory": "scissors"}
REACT_S = 2.0
WINS_NEEDED = 2
LINES = {("rock", "scissors"): "Rock smashes scissors", ("paper", "rock"): "Paper covers rock",
         ("scissors", "paper"): "Scissors cut paper"}


def judge(you, robot):
    if you == robot:
        return "draw"
    return "you" if BEATS[you] == robot else "robot"


class RockPaperScissors:
    def __init__(self, say, chime, react, gesture_now=lambda: "None", pause_gestures=lambda paused: None,
                 speaking=lambda: False, on_match_end=None, rng=None):
        self.say, self.chime, self.react = say, chime, react
        self.gesture_now = gesture_now          # fn() -> current gesture name ("Closed_Fist", ...)
        self.pause_gestures = pause_gestures
        self.speaking = speaking
        self.on_match_end = on_match_end or (lambda winner: None)
        self.rng = rng or random.Random()
        self.state = "idle"                     # idle | countdown | waiting
        self.score = {"you": 0, "robot": 0, "draws": 0}
        self.history = Counter()
        self.rounds = []
        self._voice_move = None
        self._gen = 0

    def start(self):
        self.score = {"you": 0, "robot": 0, "draws": 0}
        self.rounds = []
        self._gen += 1
        self.pause_gestures(True)
        self.say("Best of three! Show me a fist for rock, a flat hand for paper, or a peace sign for scissors. You can also just say it.")
        self._next_round(self._gen)
        return self.status()

    def stop(self, quiet=False):
        self._gen += 1
        self.state = "idle"
        self.pause_gestures(False)
        if not quiet:
            self.say("Okay, game over.")

    def choose(self):
        if self.history and self.rng.random() < 0.5:
            favourite = self.history.most_common(1)[0][0]
            return next(m for m in MOVES if BEATS[m] == favourite)     # what beats their favourite
        return self.rng.choice(MOVES)

    def _next_round(self, gen, retry=False):
        threading.Thread(target=self._round, args=(gen, retry), name="rps", daemon=True).start()

    def _round(self, gen, retry):
        self.state = "countdown"
        self._voice_move = None
        self.say("Show me again! Rock, paper, scissors, shoot!" if retry else "Rock, paper, scissors, shoot!")
        time.sleep(0.4)
        t0 = time.monotonic()
        while self.speaking() and time.monotonic() - t0 < 8 and gen == self._gen:
            time.sleep(0.05)
        self.state = "waiting"
        move, end = None, time.monotonic() + REACT_S
        while time.monotonic() < end and gen == self._gen and move is None:
            move = self._voice_move or GESTURE_MOVE.get(self.gesture_now())
            time.sleep(0.05)
        if gen != self._gen:
            return
        if move is None:
            if retry:
                self.stop(quiet=True)
                self.say("I couldn't see your hand. Let's play another time!")
                return
            return self._round(gen, True)
        self.play(move, gen)

    def voice(self, text):
        """A spoken move during a game, or None if the text isn't one."""
        if self.state == "idle":
            return None
        m = re.search(r"\b(rock|paper|scissors?|stone)\b", text.lower())
        if not m:
            return None
        move = {"stone": "rock", "scissor": "scissors"}.get(m.group(1), m.group(1))
        if self.state == "waiting" or self.state == "countdown":
            self._voice_move = move
            return move
        return None

    def play(self, you, gen=None):
        robot = self.choose()
        self.history[you] += 1
        who = judge(you, robot)
        self.rounds.append({"you": you, "robot": robot, "winner": who})
        self.state = "countdown"
        if who == "draw":
            self.score["draws"] += 1
            self.chime("boing")
            self.react("confused", 3.0, "draw")
            self.say(f"I picked {robot} too! A draw.")
        else:
            self.score[who] += 1
            line = LINES[(you, robot) if who == "you" else (robot, you)]
            if who == "you":
                self.chime("sad_trombone")
                self.react("sad", 3.0, "lost a round")
                self.say(f"I picked {robot}. {line}. You win this one!")
            else:
                self.chime("tada")
                self.react("excited", 3.0, "won a round")
                self.say(f"I picked {robot}! {line}. My point!")
        if max(self.score["you"], self.score["robot"]) >= WINS_NEEDED:
            winner = "you" if self.score["you"] > self.score["robot"] else "robot"
            self.say(f"{'You win the match' if winner == 'you' else 'I win the match'}, {self.score['you']} to {self.score['robot']}!")
            self.state = "idle"
            self.pause_gestures(False)
            self.on_match_end(winner)
            return self.status()
        self._next_round(gen if gen is not None else self._gen)
        return self.status()

    def status(self):
        return {"state": self.state, "score": self.score, "rounds": self.rounds[-5:], "seeing": self.gesture_now()}
