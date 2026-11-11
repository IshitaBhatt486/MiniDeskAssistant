"""
Lighting conditions, applied to benchmark images and video frames.

Each condition is applied in LINEAR light (sRGB decoded), the way a camera sensor sees it, then encoded
back to 8-bit sRGB. Low light is modelled as a camera with auto-exposure would produce it: less light
(`exposure`) and the ISP's analogue/digital gain (`gain`) bringing the image partly back up, which
amplifies the sensor's shot noise (signal-dependent) and read noise (constant). Same family of
corruptions as the ImageNet-C / COCO-C robustness benchmarks (brightness, contrast, noise, blur:
Hendrycks & Dietterich 2019, Michaelis et al. 2019), plus desk-specific cases: a window behind the
object (backlit), lamp colour temperature (warm / cool) and the robot turning (motion blur).

Deterministic: the noise is seeded from the image id, so every run and every model sees the same images.
"""

from __future__ import annotations

import numpy as np

_LUT = None


def _to_linear(img):
    global _LUT
    if _LUT is None:
        c = np.arange(256) / 255.0
        _LUT = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)
    return _LUT[img]


def _to_srgb(lin):
    lin = np.clip(lin, 0.0, 1.0)
    out = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)


def _sensor(img, exposure, gain, rng, shot=0.004, read=0.0025):
    lin = _to_linear(img) * exposure
    noise = rng.standard_normal(lin.shape).astype(np.float32) * np.sqrt(shot * lin + read ** 2)
    return _to_srgb((lin + noise) * gain)


def _contrast(img, k, lift=0.0):
    x = img.astype(np.float32) / 255.0
    m = x.mean()
    return np.clip(((x - m) * k + m + lift) * 255 + 0.5, 0, 255).astype(np.uint8)


def _white_balance(img, b, g, r):
    lin = _to_linear(img) * np.array([b, g, r], np.float32)   # images are BGR
    return _to_srgb(lin)


def _backlit(img):
    h = img.shape[0]
    ramp = np.linspace(3.0, 0.35, h, dtype=np.float32)[:, None, None]   # bright window at the top, subject in shadow
    return _to_srgb(_to_linear(img) * ramp)


def _motion_blur(img, k=9):
    import cv2

    kernel = np.zeros((k, k), np.float32)
    kernel[k // 2, :] = 1.0 / k
    return cv2.filter2D(img, -1, kernel)


# name -> (description, function(img, rng) -> img)
CONDITIONS = {
    "normal": ("unchanged (office light)", lambda im, rng: im),
    "dim": ("evening lamp: 30% light, gain x2", lambda im, rng: _sensor(im, 0.30, 2.0, rng)),
    "dark": ("night, one distant lamp: 10% light, gain x4", lambda im, rng: _sensor(im, 0.10, 4.0, rng)),
    "very_dark": ("almost dark: 3% light, gain x8 (heavy noise)", lambda im, rng: _sensor(im, 0.03, 8.0, rng)),
    "bright": ("sunlight on the desk: 2.5x, highlights clip", lambda im, rng: _sensor(im, 2.5, 1.0, rng)),
    "harsh": ("hard direct light: contrast x1.8", lambda im, rng: _contrast(im, 1.8, 0.05)),
    "low_contrast": ("glare / haze: contrast x0.45", lambda im, rng: _contrast(im, 0.45, 0.12)),
    "backlit": ("window behind the objects", lambda im, rng: _backlit(im)),
    "warm": ("tungsten lamp (~2700 K)", lambda im, rng: _white_balance(im, 0.55, 0.95, 1.30)),
    "cool": ("cool LED / daylight (~7500 K)", lambda im, rng: _white_balance(im, 1.30, 1.0, 0.75)),
    "motion_blur": ("robot turning: 9 px horizontal blur", lambda im, rng: _motion_blur(im)),
}

DEFAULT_IMAGE_CONDITIONS = list(CONDITIONS)
DEFAULT_VIDEO_CONDITIONS = ["normal", "dim", "dark", "backlit"]


def apply(name, img, seed=0):
    _, fn = CONDITIONS[name]
    return fn(img, np.random.default_rng(seed))
