"""The match roster, read off the broadcast scoreboard.

Doc 0 says `alliances` is what narrows bumper OCR to three candidates a side, and that a job whose
TBA lookup found nothing is still valid. That case is not rare -- the first real match analysed
had `alliances: null`, because TBA has no data for it -- and without a roster bumper OCR is an
open-vocabulary problem it cannot win. The graphic on screen already names all six teams, so it
is the fallback, and doc 0 already reserves `scoreboard_ocr` as a source for exactly this.

Two ideas do the work, and neither needs a per-venue crop region:

  * The alliance bar is the one place on screen where a wide band of saturated red sits directly
    beside a wide band of saturated blue. Finding that pair locates both cells, and which cell a
    number came from IS its alliance -- no guessing from left and right.

  * Inside a cell, the team numbers are the digits that do not change. The score changes, the
    timer changes, the ranking changes. Sampling frames across the match separates them with no
    knowledge of the layout at all.

Handing a whole cell to Tesseract does not work: the team logos beside each number are shapes it
tries to read, and the score is three times the height of the team numbers, so there is no
consistent line. Glyphs are isolated instead, grouped by the height they share, and each number is
read on its own -- a much easier question than reading a layout.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .team_id import tesseract_available

try:  # pragma: no cover
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None

STRIP_SHARE = 0.20    #: top fraction of the frame the graphic can occupy
MIN_RUN = 120         #: px; a narrower band of colour is an icon or a side panel, not a cell
UPSCALE = 4
TEAM_DIGITS = (3, 5)  #: an FRC team number, so not a score and not a fragment
ALLIANCE_SIZE = 3


def _runs(present, threshold, min_run=MIN_RUN):
    """Contiguous column ranges where a colour covers most of the bar's height."""
    on = present > threshold
    out, start = [], None
    for x, flag in enumerate(on):
        if flag and start is None:
            start = x
        elif not flag and start is not None:
            if x - start >= min_run:
                out.append((start, x - 1))
            start = None
    if start is not None and len(on) - start >= min_run:
        out.append((start, len(on) - 1))
    return out


def find_cells(frame):
    """{"red": (x0, x1, y0, y1), "blue": ...} for the alliance bar, or None."""
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    strip = frame[0:int(h * STRIP_SHARE)]
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    hh, ss, vv = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    strong = (ss > 120) & (vv > 70)
    red = strong & ((hh < 10) | (hh > 170))
    blue = strong & (hh > 100) & (hh < 130)

    bar_rows = [y for y in range(strip.shape[0])
                if red[y].sum() > w * 0.10 and blue[y].sum() > w * 0.10]
    if not bar_rows:
        return None
    y0, y1 = min(bar_rows), max(bar_rows)
    height = y1 - y0 + 1
    red_runs = _runs(red[y0:y1 + 1].sum(axis=0), height * 0.5)
    blue_runs = _runs(blue[y0:y1 + 1].sum(axis=0), height * 0.5)
    if not red_runs or not blue_runs:
        return None
    # The bar is the red run and the blue run that touch. Side panels sit far from both.
    r, b = min(((r, b) for r in red_runs for b in blue_runs),
               key=lambda rb: min(abs(rb[0][1] - rb[1][0]), abs(rb[1][1] - rb[0][0])))
    return {"red": (r[0], r[1], y0, y1), "blue": (b[0], b[1], y0, y1)}


def read_cell(frame, cell) -> list[int]:
    """Every team-number-shaped group of white glyphs in one alliance cell."""
    import cv2
    import numpy as np

    if not tesseract_available():
        return []
    x0, x1, y0, y1 = cell
    patch = frame[y0:y1 + 1, x0:x1 + 1]
    if patch.size == 0:
        return []
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    # White text on a saturated ground. A team logo is coloured, so it drops out here.
    white = ((hsv[..., 2] > 150) & (hsv[..., 1] < 90)).astype(np.uint8) * 255

    count, _, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
    glyphs = [(x, y, w, h) for i in range(1, count)
              for x, y, w, h, area in [stats[i]]
              if h >= 6 and area >= 12 and w <= h * 2.5]
    if not glyphs:
        return []

    # Team-number digits share a height; the score is far taller. The commonest height is theirs.
    mode = Counter(g[3] for g in glyphs).most_common(1)[0][0]
    same = [g for g in glyphs if abs(g[3] - mode) <= max(2, mode * 0.25)]
    if not same:
        return []

    same.sort(key=lambda g: g[0])
    gap_limit = mode * 0.9
    groups, current = [], [same[0]]
    for g in same[1:]:
        prev = current[-1]
        if g[0] - (prev[0] + prev[2]) > gap_limit or abs(g[1] - prev[1]) > mode * 0.5:
            groups.append(current)
            current = [g]
        else:
            current.append(g)
    groups.append(current)

    out = []
    for group in groups:
        gx0 = min(g[0] for g in group)
        gy0 = min(g[1] for g in group)
        gx1 = max(g[0] + g[2] for g in group)
        gy1 = max(g[1] + g[3] for g in group)
        crop = white[max(0, gy0 - 3):gy1 + 3, max(0, gx0 - 3):gx1 + 3]
        if crop.size == 0:
            continue
        big = cv2.resize(crop, (crop.shape[1] * UPSCALE, crop.shape[0] * UPSCALE),
                         interpolation=cv2.INTER_CUBIC)
        big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=0)
        text = pytesseract.image_to_string(
            cv2.bitwise_not(big),
            config="--psm 7 -c tessedit_char_whitelist=0123456789").strip()
        digits = re.sub(r"\D", "", text)
        if TEAM_DIGITS[0] <= len(digits) <= TEAM_DIGITS[1]:
            out.append(int(digits))
    return out


def roster_from_counts(counts: dict[str, dict[int, int]], frames: int) -> dict[str, list[int]]:
    """The three most persistent numbers per alliance, and only if they really persisted.

    A real majority is required so a missing team stays missing rather than being filled in with
    the best available piece of noise. Two teams and a null is a better answer than three teams
    one of which is invented.
    """
    roster = {}
    for alliance in ("red", "blue"):
        ranked = sorted(counts.get(alliance, {}).items(), key=lambda kv: (-kv[1], kv[0]))
        roster[alliance] = sorted(n for n, c in ranked[:ALLIANCE_SIZE] if c > frames / 2)
    return roster


def read_roster(video_path, sample_times, fps: float) -> dict[str, list[int]]:
    """Sample the scoreboard across the match and keep what stayed constant."""
    import cv2

    wanted = {int(round(t * fps)) for t in sample_times}
    counts: dict[str, dict[int, int]] = {"red": defaultdict(int), "blue": defaultdict(int)}
    frames = 0
    capture = cv2.VideoCapture(str(video_path))
    index, last = 0, (max(wanted) if wanted else -1)
    while index <= last:
        ok, frame = capture.read()
        if not ok:
            break
        if index in wanted:
            cells = find_cells(frame)
            if cells is not None:
                frames += 1
                for alliance, cell in cells.items():
                    for number in read_cell(frame, cell):
                        counts[alliance][number] += 1
        index += 1
    capture.release()
    if frames == 0:
        return {"red": [], "blue": []}
    return roster_from_counts(counts, frames)
