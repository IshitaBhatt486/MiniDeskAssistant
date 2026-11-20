"""
The eye animations: hardcoded keyframe tables. Nothing here is generated at run time.

    11 emotions x 5 animations = 55 (celebrating added 19 Nov 2026). When an emotion is invoked, eyes.FacePlayer picks one at random.

An animation is a list of keyframes K(time_ms, easing, fx, **pose). `easing` is the name of a pytweening
function used on the way INTO that keyframe. Pose fields not given take the emotion's BASE value:

    w, h, r      eye width, height, corner radius (pixels)
    open         height multiplier for both eyes; left, right multiply one eye (for winks)
    dx, dy       move both eyes
    lid_in       inner corner of the top lid drops this many pixels (cross)
    lid_out      outer corner drops (sad / worried)
    lid          the whole top lid drops
    cheek        a curved lower lid rises (smiling eyes)
    spread       extra distance between the eyes
    look         how much the eyes follow the user (0-1)

`fx` is a small extra drawn from this keyframe until the next: z ? ! heart tear sweat spark dizzy confetti
"""

from __future__ import annotations

from collections import namedtuple

Keyframe = namedtuple("Keyframe", "ms ease fx pose")

# "celebrating" (19 Nov 2026, buddy/): a finished task. Appended last, so the indices of the others don't change.
EMOTIONS = ("neutral", "happy", "excited", "curious", "sleepy", "sad", "confused", "scared", "annoyed", "embarrassed",
            "celebrating")

DEFAULT_POSE = {"w": 32.0, "h": 34.0, "r": 9.0, "open": 1.0, "left": 1.0, "right": 1.0, "dx": 0.0, "dy": 0.0,
                "lid_in": 0.0, "lid_out": 0.0, "lid": 0.0, "cheek": 0.0, "spread": 0.0, "look": 1.0}

BASE = {
    "neutral": {},
    "happy": {"cheek": 13.0, "h": 36.0},
    "excited": {"w": 36.0, "h": 40.0, "r": 12.0, "cheek": 7.0},
    "curious": {"left": 1.12, "right": 0.82},
    "sleepy": {"lid": 16.0, "h": 28.0, "lid_out": 3.0, "look": 0.3},
    "sad": {"lid_out": 12.0, "h": 30.0, "dy": 4.0, "look": 0.6},
    "confused": {"left": 1.1, "right": 0.62, "lid_in": 3.0, "look": 0.5},
    "scared": {"w": 26.0, "h": 42.0, "r": 12.0, "spread": 4.0, "look": 0.2},
    "annoyed": {"lid_in": 13.0, "h": 28.0, "lid": 2.0, "look": 0.8},
    "embarrassed": {"h": 28.0, "lid": 4.0, "lid_out": 5.0, "cheek": 6.0, "dy": 4.0, "look": 0.1},
    "celebrating": {"w": 36.0, "h": 38.0, "r": 12.0, "cheek": 12.0, "look": 0.4},
}


def K(ms, ease="easeInOutSine", fx=None, **pose):
    return Keyframe(ms, ease, fx, pose)


ANIMATIONS = {
    "neutral": [
        ("settle", [K(0, open=0.7), K(220, "easeOutBack"), K(1200)]),
        ("glance around", [K(0), K(300, dx=-9), K(800, dx=-9), K(1100, dx=9), K(1600, dx=9), K(1900)]),
        ("look up and back", [K(0), K(350, dy=-7), K(850, dy=-7), K(1150)]),
        ("slow squint", [K(0), K(500, lid=6), K(1100, lid=6), K(1500)]),
        ("little bob", [K(0), K(180, "easeOutQuad", dy=3), K(420, "easeOutBounce"), K(620, dy=2), K(860, "easeOutBounce")]),
    ],
    "happy": [
        ("beam", [K(0, cheek=0), K(320, "easeOutBack", cheek=15), K(1500, cheek=13)]),
        ("bounce", [K(0), K(160, "easeOutQuad", dy=-6), K(420, "easeOutBounce"), K(580, "easeOutQuad", dy=-4), K(860, "easeOutBounce")]),
        ("wink", [K(0), K(120, right=0.08), K(460, right=0.08), K(640, "easeOutBack"), K(1000)]),
        ("sway", [K(0), K(350, dx=-6, dy=-2), K(750, dx=6, dy=-2), K(1150, dx=-4), K(1450)]),
        ("hearts", [K(0, "linear", "heart", w=30, cheek=10), K(500, "easeOutBack", "heart", w=35, cheek=14), K(1000, fx="heart", w=31), K(1400, w=32)]),
    ],
    "excited": [
        ("star burst", [K(0, "linear", "spark", open=0.7), K(180, "easeOutBack", "spark", w=40, h=44), K(520, fx="spark"), K(900)]),
        ("jump jump", [K(0), K(120, "easeOutQuad", dy=-9), K(280, "easeInQuad", dy=4), K(400, "easeOutQuad", dy=-9), K(560, "easeInQuad", dy=4), K(720, "easeOutBounce")]),
        ("shake with joy", [K(0), K(70, dx=-5), K(140, dx=5), K(210, dx=-5), K(280, dx=5), K(350, dx=-4), K(420, dx=4), K(520)]),
        ("double blink", [K(0), K(80, open=0.08), K(170), K(260, open=0.08), K(380, "easeOutBack", w=40, h=44), K(1000)]),
        ("grow", [K(0, w=28, h=30), K(420, "easeOutElastic", w=42, h=46), K(1000, w=40, h=44), K(1300)]),
    ],
    "curious": [
        ("tilt look", [K(0), K(320, dx=8, dy=-3), K(1000, dx=8, dy=-3), K(1300)]),
        ("question", [K(0, "linear", "?"), K(350, fx="?", left=1.22, right=0.72), K(1200, fx="?", left=1.22, right=0.72), K(1500)]),
        ("swap brows", [K(0), K(400, left=0.82, right=1.14), K(900, left=0.82, right=1.14), K(1300)]),
        ("peer closer", [K(0), K(420, w=38, h=38, spread=-4), K(1000, w=38, h=38, spread=-4), K(1350)]),
        ("scan", [K(0), K(260, dx=-12), K(560, dx=-12), K(860, dx=12), K(1160, dx=12), K(1420)]),
    ],
    "sleepy": [
        ("nod off", [K(0), K(900, lid=24, dy=3), K(1150, "easeOutBack", lid=13, dy=-1), K(1700, lid=18)]),
        ("zzz", [K(0, "linear", "z", lid=22, look=0), K(1000, fx="z", lid=24, look=0), K(2000, fx="z", lid=24, look=0), K(2300, lid=20)]),
        ("yawn", [K(0), K(650, lid=4, h=40, w=28, lid_out=0), K(1300, lid=4, h=40, w=28, lid_out=0), K(1800, lid=20)]),
        ("heavy blink", [K(0), K(450, open=0.08), K(1000, open=0.08), K(1500), K(1900, lid=20)]),
        ("droop", [K(0), K(800, dy=5, lid_out=8), K(1500, dy=5, lid_out=8), K(1900, lid=18)]),
    ],
    "sad": [
        ("tear", [K(0, "linear", "tear"), K(800, fx="tear", dy=6), K(1600, fx="tear", dy=6), K(1900)]),
        ("look down", [K(0), K(600, dy=9, lid=4), K(1300, dy=9, lid=4), K(1700)]),
        ("sigh", [K(0), K(450, dy=-2, lid_out=8), K(1100, dy=7, lid_out=15, lid=4), K(1600)]),
        ("tremble", [K(0), K(90, dx=-1.5), K(180, dx=1.5), K(270, dx=-1.5), K(360, dx=1.5), K(450, dx=-1.5), K(540, dx=1.5), K(700)]),
        ("look away", [K(0), K(520, dx=-11, dy=5), K(1300, dx=-11, dy=5), K(1750)]),
    ],
    "confused": [
        ("what", [K(0, "linear", "?"), K(320, fx="?", left=1.2, right=0.5), K(1000, fx="?", left=1.2, right=0.5), K(1300)]),
        ("dizzy", [K(0, "linear", "dizzy", look=0), K(300, fx="dizzy", dx=5, dy=-4, look=0), K(600, fx="dizzy", dx=-5, dy=-4, look=0), K(900, fx="dizzy", dx=-5, dy=4, look=0), K(1200, fx="dizzy", dx=5, dy=4, look=0), K(1500)]),
        ("swap squint", [K(0), K(300, left=0.55, right=1.15), K(800, left=0.55, right=1.15), K(1100, left=1.15, right=0.55), K(1600, left=1.15, right=0.55), K(1900)]),
        ("double take", [K(0), K(130, "easeOutQuad", dx=11), K(300), K(420, "easeOutQuad", dx=11), K(950, dx=11), K(1200)]),
        ("blink blink", [K(0), K(100, left=0.08), K(220), K(330, right=0.08), K(450), K(800)]),
    ],
    "scared": [
        ("gasp", [K(0, "linear", "!", open=0.5), K(110, "easeOutBack", "!", w=30, h=48), K(600, fx="!", w=30, h=48), K(900)]),
        ("shiver", [K(0, "linear", "sweat"), K(60, fx="sweat", dx=-3), K(120, fx="sweat", dx=3), K(180, fx="sweat", dx=-3), K(240, fx="sweat", dx=3), K(300, fx="sweat", dx=-3), K(360, fx="sweat", dx=3), K(460)]),
        ("dart", [K(0), K(90, "easeOutQuad", dx=-14), K(380, dx=-14), K(470, "easeOutQuad", dx=14), K(760, dx=14), K(860)]),
        ("shrink", [K(0), K(320, "easeOutQuad", w=20, h=26, r=8, dy=5), K(1000, w=20, h=26, r=8, dy=5), K(1300)]),
        ("wide and worried", [K(0), K(200, "easeOutBack", h=46, lid_out=7), K(1000, h=46, lid_out=7), K(1300)]),
    ],
    "annoyed": [
        ("glare", [K(0), K(240, "easeOutQuad", lid_in=17, lid=4), K(1100, lid_in=17, lid=4), K(1400)]),
        ("eye roll", [K(0), K(240, dx=-10, dy=-4), K(480, dy=-10), K(720, dx=10, dy=-4), K(950), K(1200)]),
        ("huff", [K(0), K(160, "easeOutQuad", dy=-4, w=35), K(480, "easeOutBounce"), K(900)]),
        ("side eye", [K(0), K(240, dx=13, lid=9, lid_in=6), K(1200, dx=13, lid=9, lid_in=6), K(1500)]),
        ("shake no", [K(0), K(110, dx=-8), K(250, dx=8), K(390, dx=-7), K(530, dx=7), K(670)]),
    ],
}

ANIMATIONS["embarrassed"] = [
    ("look away", [K(0, fx="sweat"), K(260, "easeOutQuad", "sweat", dx=-14, dy=6), K(1200, fx="sweat", dx=-14, dy=6), K(1500)]),
    ("shrink down", [K(0), K(340, "easeOutQuad", "sweat", w=25, h=20, dy=10), K(1200, fx="sweat", w=25, h=20, dy=10), K(1500)]),
    ("nervous glances", [K(0, fx="sweat"), K(150, fx="sweat", dx=-10), K(420, fx="sweat", dx=-10), K(570, fx="sweat", dx=10), K(840, fx="sweat", dx=10), K(1000)]),
    ("squeeze shut", [K(0), K(180, "easeOutQuad", "sweat", open=0.15), K(800, fx="sweat", open=0.15), K(1050, "easeOutBack")]),
    ("sheepish peek", [K(0), K(300, open=0.35, dy=8), K(800, open=0.35, dy=8), K(1000, open=0.8, dx=7, dy=4), K(1500, open=0.8, dx=7, dy=4), K(1800)]),
]

ANIMATIONS["celebrating"] = [
    ("confetti", [K(0, "linear", "confetti", open=0.6), K(220, "easeOutBack", "confetti", w=40, h=42, cheek=15),
                  K(1600, fx="confetti", w=38, h=40), K(2000, fx="confetti")]),
    ("victory bounce", [K(0, fx="confetti"), K(140, "easeOutQuad", "confetti", dy=-10), K(380, "easeOutBounce", "confetti"),
                        K(520, "easeOutQuad", "confetti", dy=-8), K(760, "easeOutBounce", "confetti"),
                        K(900, "easeOutQuad", "confetti", dy=-6), K(1150, "easeOutBounce", "confetti"), K(1600)]),
    ("proud wink", [K(0, fx="spark"), K(200, "easeOutBack", "spark", cheek=15, dy=-3), K(420, "linear", "spark", right=0.08, cheek=15, dy=-3),
                    K(800, "easeOutBack", "spark", cheek=15, dy=-3), K(1400)]),
    ("spin eyes", [K(0, fx="confetti"), K(180, fx="confetti", dx=-8, dy=-5), K(360, fx="confetti", dx=8, dy=-5),
                   K(540, fx="confetti", dx=8, dy=5), K(720, fx="confetti", dx=-8, dy=5), K(900, fx="confetti", dx=-8, dy=-5),
                   K(1080, "easeOutBack", "confetti"), K(1500)]),
    ("happy dance", [K(0, "linear", "heart"), K(160, "easeOutQuad", "heart", dx=-7, dy=-4), K(320, "easeOutQuad", "heart", dx=7, dy=-4),
                     K(480, "easeOutQuad", "heart", dx=-7, dy=-4), K(640, "easeOutQuad", "heart", dx=7, dy=-4),
                     K(900, "easeOutBounce", "confetti", cheek=15), K(1600, fx="confetti")]),
]

# Blinks: (ms, open). One is chosen at random each time.
BLINKS = (
    ((0, 1.0), (70, 0.05), (150, 1.0)),
    ((0, 1.0), (90, 0.05), (140, 0.05), (240, 1.0)),
    ((0, 1.0), (60, 0.05), (130, 1.0), (210, 0.05), (290, 1.0)),
)
