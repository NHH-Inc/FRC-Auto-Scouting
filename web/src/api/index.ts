// The only surface component 3 uses to reach component 2.
//
// Doc 0: "Component 3 only ever talks to component 2 over HTTP." Nothing in web/ imports
// from analysis/ or ingest/, shells out, or calls TBA or YouTube directly. Two
// implementations of one interface: the HTTP client, and a fixture client so the whole UI
// runs with no backend at all.

import type {
  ContractViolation,
  Correction,
  Job,
  ScoutEvent,
  Track,
} from '../contracts';
import type { Accuracy, ExportResult, TeamStatsSummary } from './shapes';

export interface Parsed<T> {
  data: T;
  violations: ContractViolation[];
}

export interface EventQuery {
  /** Contract E: ?min_confidence=0.5 */
  minConfidence?: number;
  /** Contract E: ?raw=true returns uncorrected model output. */
  raw?: boolean;
}

export interface CreateJobInput {
  url: string;
  /** Optional per Contract E. Component 2 resolves it from video metadata if omitted. */
  matchId?: string | null;
}

export interface ExportInput {
  matchIds: string[];
  mode: 'raw' | 'aggregate';
}

export interface ScoutingApi {
  readonly mode: 'http' | 'fixture';

  listJobs(): Promise<Parsed<Job[]>>;
  getJob(jobId: string): Promise<Parsed<Job | null>>;
  createJob(input: CreateJobInput): Promise<Parsed<Job>>;
  deleteJob(jobId: string): Promise<void>;
  /**
   * Doc 3: failures "need a retry path that does not require re-pasting the link."
   * Contract E has no retry endpoint, so this re-POSTs /api/jobs with the video_id and
   * match_id already on the job record. See contracts/OPEN_QUESTIONS.md #5.
   */
  retryJob(job: Job): Promise<Parsed<Job>>;

  getEvents(matchId: string, query?: EventQuery): Promise<Parsed<ScoutEvent[]>>;
  getTracks(matchId: string): Promise<Parsed<Track[]>>;
  getAccuracy(matchId: string): Promise<Accuracy>;
  /**
   * Contract E has no endpoint that lists corrections (OPEN_QUESTIONS.md #3). The HTTP
   * client returns null here and the UI falls back to diffing raw against corrected; the
   * fixture client can return them properly.
   */
  getCorrections(matchId: string): Promise<Parsed<Correction[]> | null>;

  createEvent(event: Omit<ScoutEvent, 'eventId'>): Promise<Parsed<ScoutEvent>>;
  patchEvent(eventId: string, fields: Partial<ScoutEvent>): Promise<Parsed<ScoutEvent>>;
  deleteEvent(eventId: string): Promise<void>;

  getTeamStats(team: number, eventKey?: string): Promise<TeamStatsSummary>;
  exportSheets(input: ExportInput): Promise<ExportResult>;

  /** GET /api/video/:job_id -- the local segment file the player streams. */
  videoUrl(job: Job): string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly url: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

let cached: ScoutingApi | null = null;

/**
 * Picks the client from VITE_API_MODE. Defaults to fixture so a fresh clone runs with
 * `npm install && npm run dev` and nothing else -- doc 0: "Component 3 builds the whole UI
 * against fixture data with no backend running."
 */
export async function getApi(): Promise<ScoutingApi> {
  if (cached) return cached;
  const mode = (import.meta.env.VITE_API_MODE as string) ?? 'fixture';
  if (mode === 'http') {
    const { HttpApi } = await import('./http');
    cached = new HttpApi((import.meta.env.VITE_API_BASE as string) ?? '/api');
  } else {
    const { FixtureApi } = await import('./fixture');
    cached = new FixtureApi();
  }
  return cached;
}
