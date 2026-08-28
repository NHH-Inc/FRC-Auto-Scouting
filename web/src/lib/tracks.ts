// Box interpolation for the overlay.
//
// Contract C: "Box sampling rate does not need to match video frame rate. Component 3
// interpolates between samples." The fixture samples at 5 Hz against 30 fps video, so five
// out of every six rendered frames are interpolated. If this is wrong the boxes visibly
// stair-step, which is the fastest way to notice a regression here.

import type { Box, Track } from '../contracts';

/**
 * Contract C also says the sample rate should be stated in the job result -- but no
 * Contract E endpoint exposes result.json to component 3 (OPEN_QUESTIONS.md #2), so we
 * infer it from the data instead. Median spacing, because a track that drops frames has a
 * few long gaps that would drag a mean.
 */
export function estimateSampleRate(tracks: Track[], fallbackHz = 5): number {
  const gaps: number[] = [];
  for (const tr of tracks) {
    for (let i = 1; i < tr.boxes.length; i++) {
      const d = tr.boxes[i].t - tr.boxes[i - 1].t;
      if (d > 1e-6) gaps.push(d);
    }
  }
  if (gaps.length === 0) return fallbackHz;
  gaps.sort((a, b) => a - b);
  const median = gaps[gaps.length >> 1];
  return median > 0 ? 1 / median : fallbackHz;
}

/** Index of the last box at or before t, or -1 if t precedes every sample. */
function lastAtOrBefore(boxes: Box[], t: number): number {
  let lo = 0;
  let hi = boxes.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (boxes[mid].t <= t) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}

/**
 * How large a gap between two samples may be before we stop interpolating across it,
 * as a multiple of the sample period.
 *
 * This matters because of doc 1: the analysis backend detects broadcast shot changes and
 * "those segments should be detected and skipped, not analyzed", and result.json reports
 * frames_skipped_shot_change. A skipped segment leaves a hole in a track's boxes, but
 * Contract C has no way to mark one -- boxes is a flat array. Interpolating across the hole
 * would draw a robot gliding smoothly through footage nobody ever looked at, which is
 * fabricated data presented at the same confidence as real data.
 *
 * So: interpolate within a few sample periods, and go blank across anything longer.
 * Raised with the other two as OPEN_QUESTIONS.md #8.
 */
export const MAX_INTERPOLATION_GAP_PERIODS = 3;

/**
 * The track's box at time t, linearly interpolated between samples.
 *
 * Returns null when t is outside the track's lifetime -- a track that has not appeared yet
 * or has already been lost must not draw a box. `holdSeconds` tolerates the gap between the
 * last sample and the end of that track's presence so the box does not flicker out one
 * sample period early; it does not extend the track beyond a real disappearance.
 *
 * Also returns null inside a gap too long to bridge honestly (see above).
 */
export function boxAt(track: Track, t: number, holdSeconds = 0): Box | null {
  const b = track.boxes;
  if (b.length === 0) return null;
  if (t < b[0].t - 1e-9) return null;
  if (t > b[b.length - 1].t + holdSeconds + 1e-9) return null;

  const i = lastAtOrBefore(b, t);
  if (i < 0) return null;
  if (i === b.length - 1) return b[i];

  const a = b[i];
  const c = b[i + 1];
  const span = c.t - a.t;
  if (span <= 1e-9) return a;

  // holdSeconds carries the sample period, so it is also the yardstick for "too long".
  if (holdSeconds > 0 && span > holdSeconds * MAX_INTERPOLATION_GAP_PERIODS) {
    // Inside an unobserved stretch. Hold the last real sample briefly, then show nothing
    // rather than inventing positions.
    return t <= a.t + holdSeconds ? a : null;
  }

  const u = (t - a.t) / span;
  return {
    t,
    x: a.x + (c.x - a.x) * u,
    y: a.y + (c.y - a.y) * u,
    w: a.w + (c.w - a.w) * u,
    h: a.h + (c.h - a.h) * u,
  };
}

/** Every track visible at time t, with its interpolated box. */
export function visibleBoxes(
  tracks: Track[],
  t: number,
  holdSeconds = 0
): Array<{ track: Track; box: Box }> {
  const out: Array<{ track: Track; box: Box }> = [];
  for (const track of tracks) {
    const box = boxAt(track, t, holdSeconds);
    if (box) out.push({ track, box });
  }
  // Painter's order: boxes lower on screen are nearer the camera and drawn last.
  out.sort((p, q) => p.box.y - q.box.y);
  return out;
}
