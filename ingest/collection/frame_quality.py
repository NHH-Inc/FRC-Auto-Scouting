"""Reject broadcast frames that contain no field to look at.

An FRC broadcast is not all match footage. It cuts to the FIRST logo, to "RED ALLIANCE WINS"
cards, to sponsor stings and crowd shots. Sampling every N seconds picks those up indifferently,
and they are worse than useless as training data: a label model will happily draw "robots" on a
FIRST logo -- ours drew one or two on every single one -- and a detector trained on that learns
that grey gradients contain robots.

Thresholds here are measured, not guessed. Across 557 frames from ten different 2026 events:

                        flat_share            brightness
    gameplay            0.135 - 0.185         100 - 137
    "ALLIANCE WINS"     ~0.30                 186 - 189
    FIRST logo card     0.69                  184

Both features separate with a wide gap, so the cutoffs sit in the empty space between the two
populations rather than clipping the edge of either.

This is deliberately not a model. It is cheap, it runs on any machine without a GPU, and its
mistakes are inspectable -- every rejection names the reason that fired.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

#: Fraction of the frame allowed to sit in one coarse colour bucket. Studio cards are large flat
#: fills; a real camera shot of a field never is.
MAX_FLAT_SHARE = 0.30

#: Mean HSV value. Graphics cards are lit far brighter than an arena floor.
MAX_BRIGHTNESS = 150.0

#: Below this the frame is a fade-to-black or a blown cut, with nothing to label either way.
MIN_BRIGHTNESS = 35.0

#: Contrast floor. A frame with almost no tonal variation is a solid card or a dissolve.
MIN_STDDEV = 18.0

#: Near-duplicate detection by perceptual hash was tried and removed. FRC broadcasts use a fixed
#: wide camera, so the DCT signature of a frame barely moves even when the play does: at a Hamming
#: threshold of 4 it discarded 172 of 557 frames that differed in match clock, score and robot
#: positions. Held graphic cards -- the thing dedup was meant to catch -- are already rejected by
#: the rules above, so the check cost real gameplay and bought nothing.


@dataclass(frozen=True)
class FrameVerdict:
    keep: bool
    reason: str
    flat_share: float
    brightness: float
    stddev: float
    phash: int


def _phash(gray: np.ndarray) -> int:
    """64-bit perceptual hash. Robust to compression, sensitive to actual content change."""
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    freq = cv2.dct(small)[:8, :8]
    flat = freq.flatten()[1:]  # drop DC, which only encodes overall brightness
    bits = flat > np.median(flat)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def measure(image_path: Path | str) -> FrameVerdict:
    """Classify one frame. Reads at reduced size -- full resolution buys nothing here."""
    img = cv2.imread(str(image_path))
    if img is None:
        return FrameVerdict(False, "unreadable", 0.0, 0.0, 0.0, 0)

    small = cv2.resize(img, (320, 180), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    brightness = float(cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[:, :, 2].mean())
    stddev = float(gray.std())

    # Dominant-colour share on a coarse 8x8x8 quantisation.
    q = (small // 32).astype(np.int32)
    codes = q[:, :, 0] * 64 + q[:, :, 1] * 8 + q[:, :, 2]
    _, counts = np.unique(codes, return_counts=True)
    flat_share = float(counts.max()) / codes.size

    phash = _phash(gray)

    if flat_share > MAX_FLAT_SHARE:
        reason = "graphic_card"          # logo, sponsor sting, alliance result screen
    elif brightness > MAX_BRIGHTNESS:
        reason = "overbright_graphic"
    elif brightness < MIN_BRIGHTNESS:
        reason = "too_dark"
    elif stddev < MIN_STDDEV:
        reason = "no_contrast"
    else:
        return FrameVerdict(True, "ok", flat_share, brightness, stddev, phash)

    return FrameVerdict(False, reason, flat_share, brightness, stddev, phash)


def filter_frames(paths: list[Path]) -> list[tuple[Path, FrameVerdict]]:
    """Classify a sequence of frames, in order."""
    return [(path, measure(path)) for path in paths]
