// Formatting, labels, and the one time conversion component 3 owns.

import type { EventType, JobStatus, Phase, Source } from '../contracts';

/** mm:ss.mmm -- segment time, three decimal places, matching the contract's precision. */
export function fmtTime(t: number): string {
  const sign = t < 0 ? '-' : '';
  const abs = Math.abs(t);
  const m = Math.floor(abs / 60);
  const s = abs - m * 60;
  return `${sign}${m}:${s.toFixed(3).padStart(6, '0')}`;
}

export function fmtClock(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t - m * 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function fmtSeconds(s: number | null, digits = 2): string {
  return s == null ? '--' : `${s.toFixed(digits)}s`;
}

export function fmtPercent(x: number | null, digits = 0): string {
  return x == null ? '--' : `${(x * 100).toFixed(digits)}%`;
}

export function fmtSigned(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

/**
 * Segment time -> position in the original YouTube video.
 *
 * Doc 0: "t_seconds is always relative to the start of the segment... To get a position in
 * the original video, add start_offset from the job record. Component 3 does that
 * conversion when linking to YouTube; nothing else ever should."
 *
 * This function and youtubeUrlAt() are the only places in web/ that add startOffset.
 */
export function toOriginalVideoTime(tSeconds: number, startOffset: number): number {
  return tSeconds + startOffset;
}

export function youtubeUrlAt(videoId: string, tSeconds: number, startOffset: number): string {
  const at = Math.max(0, Math.floor(toOriginalVideoTime(tSeconds, startOffset)));
  return `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}&t=${at}s`;
}

export const EVENT_LABEL: Record<EventType, string> = {
  match_start: 'Match start',
  match_end: 'Match end',
  phase_change: 'Phase change',
  shot_attempt: 'Shot attempt',
  shot_made: 'Shot made',
  reload: 'Reload',
  defense_start: 'Defense start',
  defense_end: 'Defense end',
  immobile_start: 'Immobile start',
  immobile_end: 'Immobile end',
  foul: 'Foul',
};

export const PHASE_LABEL: Record<Phase, string> = {
  auto: 'Auto',
  teleop: 'Teleop',
  endgame: 'Endgame',
  unknown: 'Unknown',
};

export const SOURCE_LABEL: Record<Source, string> = {
  model: 'Model',
  scoreboard_ocr: 'Scoreboard OCR',
  tba: 'TBA',
  manual: 'Manual',
};

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'Queued',
  downloading: 'Downloading',
  downloaded: 'Downloaded',
  analyzing: 'Analyzing',
  complete: 'Complete',
  failed: 'Failed',
};

/** Statuses where the job is still moving and the queue should keep polling. */
export const ACTIVE_STATUSES: ReadonlySet<JobStatus> = new Set<JobStatus>([
  'queued',
  'downloading',
  'downloaded',
  'analyzing',
]);

/** A short glyph per event type, for the dense timeline rows. */
export const EVENT_GLYPH: Record<EventType, string> = {
  match_start: '|',
  match_end: '|',
  phase_change: '|',
  shot_attempt: 'o',
  shot_made: '*',
  reload: '+',
  defense_start: 'D',
  defense_end: 'd',
  immobile_start: 'X',
  immobile_end: 'x',
  foul: '!',
};

/**
 * Extract an 11-character YouTube ID from whatever the user pasted.
 * Returns null rather than guessing, so the form can say so instead of queueing garbage.
 */
export function parseVideoId(input: string): string | null {
  const s = input.trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(s)) return s;
  const patterns = [
    /[?&]v=([A-Za-z0-9_-]{11})/,
    /youtu\.be\/([A-Za-z0-9_-]{11})/,
    /youtube\.com\/embed\/([A-Za-z0-9_-]{11})/,
    /youtube\.com\/live\/([A-Za-z0-9_-]{11})/,
    /youtube\.com\/shorts\/([A-Za-z0-9_-]{11})/,
  ];
  for (const p of patterns) {
    const m = s.match(p);
    if (m) return m[1];
  }
  return null;
}

/** TBA match keys are lowercase, e.g. 2026casf_qm42. */
export function isMatchKey(s: string): boolean {
  return /^[0-9]{4}[a-z0-9]+_[a-z0-9]+$/.test(s.trim());
}
