// Contract E, spoken over HTTP to component 2.
//
// Every endpoint here is one from doc 0. Nothing is invented except where noted, and each
// exception points at contracts/OPEN_QUESTIONS.md. Errors come back as standard status
// codes with {"error": "message"}, per the contract.

import {
  ViolationLog,
  eventFieldsToWire,
  parseEvent,
  parseJob,
  parseTrack,
  type Job,
  type ScoutEvent,
  type Track,
  type WireEvent,
  type WireJob,
  type WireTrack,
} from '../contracts';
import {
  ApiError,
  type CreateJobInput,
  type EventQuery,
  type ExportInput,
  type Parsed,
  type ScoutingApi,
} from './index';
import {
  parseAccuracy,
  parseExportResult,
  parseTeamStats,
  type Accuracy,
  type ExportResult,
  type TeamStatsSummary,
  type WireAccuracy,
  type WireExportResult,
  type WireTeamStats,
} from './shapes';

export class HttpApi implements ScoutingApi {
  readonly mode = 'http' as const;

  constructor(private readonly base: string) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const url = `${this.base}${path}`;
    let res: Response;
    try {
      res = await fetch(url, {
        ...init,
        headers: {
          Accept: 'application/json',
          ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
          ...init?.headers,
        },
      });
    } catch (cause) {
      throw new ApiError(`Could not reach the ingest service at ${url}`, 0, url);
    }
    if (!res.ok) {
      let message = `${res.status} ${res.statusText}`;
      try {
        const body = (await res.json()) as { error?: string };
        if (body?.error) message = body.error;
      } catch {
        // non-JSON error body; the status line is all we have
      }
      throw new ApiError(message, res.status, url);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  // ---- jobs

  async listJobs(): Promise<Parsed<Job[]>> {
    const log = new ViolationLog();
    const raw = await this.request<WireJob[]>('/jobs');
    const data = raw.map((j) => parseJob(j, log)).filter((j): j is Job => j !== null);
    return { data, violations: log.items };
  }

  async getJob(jobId: string): Promise<Parsed<Job | null>> {
    const log = new ViolationLog();
    const raw = await this.request<WireJob>(`/jobs/${encodeURIComponent(jobId)}`);
    return { data: parseJob(raw, log), violations: log.items };
  }

  async createJob(input: CreateJobInput): Promise<Parsed<Job>> {
    const log = new ViolationLog();
    const body: Record<string, unknown> = { url: input.url };
    // match_id is optional on job creation; omit rather than send null so component 2 can
    // tell "resolve it for me" from "it is definitively unknown".
    if (input.matchId) body.match_id = input.matchId;
    const raw = await this.request<WireJob>('/jobs', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    const job = parseJob(raw, log);
    if (!job) throw new ApiError('Ingest returned a job that failed contract validation', 200, '/jobs');
    return { data: job, violations: log.items };
  }

  async deleteJob(jobId: string): Promise<void> {
    await this.request<void>(`/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' });
  }

  async retryJob(job: Job): Promise<Parsed<Job>> {
    // No retry endpoint in Contract E (OPEN_QUESTIONS.md #5). Re-POST from the job record
    // so the user never re-pastes the link. This mints a new job_id.
    return this.createJob({
      url: `https://www.youtube.com/watch?v=${job.videoId}`,
      matchId: job.matchId,
    });
  }

  // ---- match data

  async getEvents(matchId: string, query: EventQuery = {}): Promise<Parsed<ScoutEvent[]>> {
    const log = new ViolationLog();
    const qs = new URLSearchParams();
    if (query.minConfidence != null) qs.set('min_confidence', String(query.minConfidence));
    if (query.raw) qs.set('raw', 'true');
    const suffix = qs.toString() ? `?${qs}` : '';
    const raw = await this.request<WireEvent[]>(
      `/matches/${encodeURIComponent(matchId)}/events${suffix}`
    );
    const data = raw
      .map((e) => parseEvent(e, log))
      .filter((e): e is ScoutEvent => e !== null)
      .sort((a, b) => a.tSeconds - b.tSeconds);
    return { data, violations: log.items };
  }

  async getTracks(matchId: string): Promise<Parsed<Track[]>> {
    const log = new ViolationLog();
    const raw = await this.request<WireTrack[]>(`/matches/${encodeURIComponent(matchId)}/tracks`);
    const data = raw.map((t) => parseTrack(t, log)).filter((t): t is Track => t !== null);
    return { data, violations: log.items };
  }

  async getAccuracy(matchId: string): Promise<Accuracy> {
    const raw = await this.request<WireAccuracy>(
      `/matches/${encodeURIComponent(matchId)}/accuracy`
    );
    return parseAccuracy(raw);
  }

  async getCorrections(): Promise<null> {
    // No such endpoint in Contract E. Returning null tells the caller to fall back to
    // diffing raw against corrected. See OPEN_QUESTIONS.md #3.
    return null;
  }

  // ---- corrections

  async createEvent(event: Omit<ScoutEvent, 'eventId'>): Promise<Parsed<ScoutEvent>> {
    const log = new ViolationLog();
    const raw = await this.request<WireEvent>('/events', {
      method: 'POST',
      body: JSON.stringify({
        ...eventFieldsToWire(event as Partial<ScoutEvent>),
        schema_version: 1,
        source: 'manual',
      }),
    });
    const parsed = parseEvent(raw, log);
    if (!parsed) throw new ApiError('Created event failed contract validation', 200, '/events');
    return { data: parsed, violations: log.items };
  }

  async patchEvent(eventId: string, fields: Partial<ScoutEvent>): Promise<Parsed<ScoutEvent>> {
    const log = new ViolationLog();
    const raw = await this.request<WireEvent>(`/events/${encodeURIComponent(eventId)}`, {
      method: 'PATCH',
      body: JSON.stringify(eventFieldsToWire(fields)),
    });
    const parsed = parseEvent(raw, log);
    if (!parsed) throw new ApiError('Patched event failed contract validation', 200, '/events');
    return { data: parsed, violations: log.items };
  }

  async deleteEvent(eventId: string): Promise<void> {
    await this.request<void>(`/events/${encodeURIComponent(eventId)}`, { method: 'DELETE' });
  }

  // ---- stats and export

  async getTeamStats(team: number, eventKey?: string): Promise<TeamStatsSummary> {
    const qs = eventKey ? `?event_key=${encodeURIComponent(eventKey)}` : '';
    const raw = await this.request<WireTeamStats>(`/teams/${team}/stats${qs}`);
    return parseTeamStats(raw);
  }

  async exportSheets(input: ExportInput): Promise<ExportResult> {
    const raw = await this.request<WireExportResult>('/export/sheets', {
      method: 'POST',
      body: JSON.stringify({ match_ids: input.matchIds, mode: input.mode }),
    });
    return parseExportResult(raw);
  }

  videoUrl(job: Job): string {
    return `${this.base}/video/${encodeURIComponent(job.jobId)}`;
  }
}
