// The contract layer. Everything component 2 sends crosses through this file and nothing
// else in web/ is allowed to touch a snake_case key.
//
// Doc 0: "snake_case in JSON, SQL, C++, and Python. camelCase only inside TypeScript,
// converted at the API boundary." So: Wire* types mirror /contracts/*.schema.json exactly,
// the domain types below are camelCase, and parse*/serialize* are the only crossing points.
//
// Doc 0 also says: "Anything unrecognized is a bug, not a fallback." These parsers do not
// coerce or default unknown enum values. They collect violations and hand them back so the
// UI can show them, and drop the offending row rather than pretending it was fine.

// ---------------------------------------------------------------- closed sets

export const PHASES = ['auto', 'teleop', 'endgame', 'unknown'] as const;
export const ALLIANCES = ['red', 'blue'] as const;
export const JOB_STATUSES = [
  'queued',
  'downloading',
  'downloaded',
  'analyzing',
  'complete',
  'failed',
] as const;
export const EVENT_TYPES = [
  'match_start',
  'match_end',
  'phase_change',
  'shot_attempt',
  'shot_made',
  'reload',
  'defense_start',
  'defense_end',
  'immobile_start',
  'immobile_end',
  'foul',
] as const;
export const SOURCES = ['model', 'scoreboard_ocr', 'tba', 'manual'] as const;
export const CORRECTION_ACTIONS = ['edit', 'delete', 'create'] as const;

export type Phase = (typeof PHASES)[number];
export type Alliance = (typeof ALLIANCES)[number];
export type JobStatus = (typeof JOB_STATUSES)[number];
export type EventType = (typeof EVENT_TYPES)[number];
export type Source = (typeof SOURCES)[number];
export type CorrectionAction = (typeof CORRECTION_ACTIONS)[number];

export const SCHEMA_VERSION = 1;

/** Event types that describe the match rather than a robot. These carry no team or track. */
export const MATCH_LEVEL_EVENTS: ReadonlySet<EventType> = new Set<EventType>([
  'match_start',
  'match_end',
  'phase_change',
]);

// ---------------------------------------------------------------- wire types

export interface WireJob {
  schema_version: number;
  job_id: string;
  match_id: string | null;
  video_id: string;
  local_path: string | null;
  start_offset: number;
  // Null until the download reports them; guaranteed non-null once status is
  // downloaded/analyzing/complete (job.schema.json enforces that conditionally).
  duration: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  status: string;
  alliances: { red: number[]; blue: number[] } | null;
  tba_score: { red: number; blue: number } | null;
  error?: string | null;
  /** Not in Contract A. See contracts/OPEN_QUESTIONS.md #4 -- read if present, never required. */
  progress?: number | null;
  stage?: string | null;
  created_at?: string | null;
}

export interface WireEvent {
  schema_version: number;
  job_id: string;
  match_id: string;
  event_id: string;
  team: number | null;
  track_id: number | null;
  t_seconds: number;
  phase: string;
  event_type: string;
  confidence: number;
  field_x: number | null;
  field_y: number | null;
  source: string;
}

export interface WireBox {
  t: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface WireTrack {
  schema_version: number;
  track_id: number;
  team: number | null;
  alliance: string | null;
  boxes: WireBox[];
}

export interface WireCorrection {
  correction_id: string;
  event_id: string;
  action: string;
  fields: Partial<WireEvent> | null;
  created_at: string;
}

// ---------------------------------------------------------------- domain types

export interface Job {
  jobId: string;
  matchId: string | null;
  videoId: string;
  localPath: string | null;
  /** Seconds. Add to an event's tSeconds to get a position in the ORIGINAL video. */
  startOffset: number;
  duration: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  status: JobStatus;
  alliances: { red: number[]; blue: number[] } | null;
  tbaScore: { red: number; blue: number } | null;
  error: string | null;
  progress: number | null;
  stage: string | null;
  createdAt: string | null;
}

/**
 * A job whose media metadata has arrived. The player and the timeline need real numbers for
 * duration/fps/width/height, and only a downloaded job has them -- so they narrow to this
 * rather than defaulting a duration and silently rendering a wrong scrub bar.
 */
export interface PlayableJob extends Job {
  localPath: string;
  duration: number;
  fps: number;
  width: number;
  height: number;
}

export function isPlayable(job: Job | null): job is PlayableJob {
  return (
    job != null &&
    typeof job.localPath === 'string' &&
    job.localPath.length > 0 &&
    job.duration != null &&
    job.fps != null &&
    job.width != null &&
    job.height != null &&
    job.duration > 0
  );
}

export interface ScoutEvent {
  jobId: string;
  matchId: string;
  eventId: string;
  team: number | null;
  trackId: number | null;
  /** Float seconds relative to the start of the SEGMENT, never the original video. */
  tSeconds: number;
  phase: Phase;
  eventType: EventType;
  /** 0..1. Never a percentage. */
  confidence: number;
  fieldX: number | null;
  fieldY: number | null;
  source: Source;
}

export interface Box {
  t: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Track {
  trackId: number;
  team: number | null;
  alliance: Alliance | null;
  boxes: Box[];
}

export interface Correction {
  correctionId: string;
  eventId: string;
  action: CorrectionAction;
  fields: Partial<ScoutEvent> | null;
  createdAt: string;
}

// ---------------------------------------------------------------- violations

export interface ContractViolation {
  what: string;
  detail: string;
  raw: unknown;
}

export class ViolationLog {
  readonly items: ContractViolation[] = [];
  add(what: string, detail: string, raw: unknown) {
    this.items.push({ what, detail, raw });
  }
  get ok() {
    return this.items.length === 0;
  }
}

function oneOf<T extends string>(
  allowed: readonly T[],
  value: unknown,
  field: string,
  raw: unknown,
  log: ViolationLog
): T | null {
  if (typeof value === 'string' && (allowed as readonly string[]).includes(value)) {
    return value as T;
  }
  log.add(field, `${JSON.stringify(value)} is not one of ${allowed.join(' | ')}`, raw);
  return null;
}

function checkVersion(v: unknown, kind: string, raw: unknown, log: ViolationLog) {
  if (v !== SCHEMA_VERSION) {
    // Additive bumps stay backward compatible, so this is a warning, not a drop.
    log.add(kind, `schema_version ${JSON.stringify(v)} != ${SCHEMA_VERSION}`, raw);
  }
}

// ---------------------------------------------------------------- parsers

export function parseJob(raw: WireJob, log: ViolationLog): Job | null {
  checkVersion(raw.schema_version, 'job.schema_version', raw, log);
  const status = oneOf(JOB_STATUSES, raw.status, 'job.status', raw, log);
  if (!status) return null;
  return {
    jobId: raw.job_id,
    matchId: raw.match_id ?? null,
    videoId: raw.video_id,
    localPath: raw.local_path ?? null,
    startOffset: raw.start_offset,
    duration: raw.duration,
    fps: raw.fps,
    width: raw.width,
    height: raw.height,
    status,
    alliances: raw.alliances ?? null,
    tbaScore: raw.tba_score ?? null,
    error: raw.error ?? null,
    progress: typeof raw.progress === 'number' ? raw.progress : null,
    stage: raw.stage ?? null,
    createdAt: raw.created_at ?? null,
  };
}

export function parseEvent(raw: WireEvent, log: ViolationLog): ScoutEvent | null {
  checkVersion(raw.schema_version, 'event.schema_version', raw, log);
  const phase = oneOf(PHASES, raw.phase, 'event.phase', raw, log);
  const eventType = oneOf(EVENT_TYPES, raw.event_type, 'event.event_type', raw, log);
  const source = oneOf(SOURCES, raw.source, 'event.source', raw, log);
  if (!phase || !eventType || !source) return null;
  if (typeof raw.confidence !== 'number' || raw.confidence < 0 || raw.confidence > 1) {
    log.add('event.confidence', `${JSON.stringify(raw.confidence)} is not a float 0..1`, raw);
    return null;
  }
  return {
    jobId: raw.job_id,
    matchId: raw.match_id,
    eventId: raw.event_id,
    team: raw.team ?? null,
    // Nullable pending contracts/OPEN_QUESTIONS.md #1.
    trackId: raw.track_id ?? null,
    tSeconds: raw.t_seconds,
    phase,
    eventType,
    confidence: raw.confidence,
    fieldX: raw.field_x ?? null,
    fieldY: raw.field_y ?? null,
    source,
  };
}

export function parseTrack(raw: WireTrack, log: ViolationLog): Track | null {
  checkVersion(raw.schema_version, 'track.schema_version', raw, log);
  let alliance: Alliance | null = null;
  if (raw.alliance != null) {
    alliance = oneOf(ALLIANCES, raw.alliance, 'track.alliance', raw, log);
    if (!alliance) return null;
  }
  return {
    trackId: raw.track_id,
    team: raw.team ?? null,
    alliance,
    boxes: raw.boxes ?? [],
  };
}

export function parseCorrection(raw: WireCorrection, log: ViolationLog): Correction | null {
  const action = oneOf(CORRECTION_ACTIONS, raw.action, 'correction.action', raw, log);
  if (!action) return null;
  return {
    correctionId: raw.correction_id,
    eventId: raw.event_id,
    action,
    fields: raw.fields ? eventFieldsToDomain(raw.fields) : null,
    createdAt: raw.created_at,
  };
}

// ---------------------------------------------------------------- serializers

const EVENT_KEY_MAP: Record<keyof ScoutEvent, keyof WireEvent> = {
  jobId: 'job_id',
  matchId: 'match_id',
  eventId: 'event_id',
  team: 'team',
  trackId: 'track_id',
  tSeconds: 't_seconds',
  phase: 'phase',
  eventType: 'event_type',
  confidence: 'confidence',
  fieldX: 'field_x',
  fieldY: 'field_y',
  source: 'source',
};
const WIRE_KEY_MAP = Object.fromEntries(
  Object.entries(EVENT_KEY_MAP).map(([k, v]) => [v, k])
) as Record<string, keyof ScoutEvent>;

/** camelCase patch -> snake_case patch, for PATCH /api/events/:event_id. */
export function eventFieldsToWire(fields: Partial<ScoutEvent>): Partial<WireEvent> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fields)) {
    const wireKey = EVENT_KEY_MAP[k as keyof ScoutEvent];
    if (wireKey) out[wireKey] = v;
  }
  return out as Partial<WireEvent>;
}

export function eventFieldsToDomain(fields: Partial<WireEvent>): Partial<ScoutEvent> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fields)) {
    const domainKey = WIRE_KEY_MAP[k];
    if (domainKey) out[domainKey] = v;
  }
  return out as Partial<ScoutEvent>;
}

export function eventToWire(e: ScoutEvent): WireEvent {
  return {
    schema_version: SCHEMA_VERSION,
    job_id: e.jobId,
    match_id: e.matchId,
    event_id: e.eventId,
    team: e.team,
    track_id: e.trackId,
    t_seconds: e.tSeconds,
    phase: e.phase,
    event_type: e.eventType,
    confidence: e.confidence,
    field_x: e.fieldX,
    field_y: e.fieldY,
    source: e.source,
  };
}
