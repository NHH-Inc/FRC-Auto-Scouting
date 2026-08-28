// The fixture client.
//
// Doc 0: "Component 3 builds the whole UI against fixture data with no backend running."
// This implements the same ScoutingApi as the HTTP client, backed by /fixtures/. It is not
// a mock in the testing sense -- it serves the real golden data, so anything that renders
// here renders against component 2 too.
//
// It also fakes the parts of the system that are inherently stateful: a job queue that
// advances through statuses, and a corrections layer stacked on top of the raw events. The
// raw events are never mutated, which is the same rule the real database follows.

import {
  ViolationLog,
  eventToWire,
  parseCorrection,
  parseEvent,
  parseJob,
  parseTrack,
  type Correction,
  type Job,
  type ScoutEvent,
  type Track,
  type WireCorrection,
  type WireEvent,
  type WireJob,
  type WireTrack,
} from '../contracts';
import { applyCorrections } from '../lib/corrections';
import { accuracyReport, computeTeamStats } from '../lib/stats';
import {
  ApiError,
  type CreateJobInput,
  type EventQuery,
  type ExportInput,
  type Parsed,
  type ScoutingApi,
} from './index';
import type { Accuracy, ExportResult, TeamStatsSummary } from './shapes';

/** Vite serves /fixtures as its publicDir, so the golden set is at the site root. */
const FIXTURE_ROOT =
  (import.meta.env.VITE_FIXTURE_ROOT as string | undefined) ?? '/2026casf_qm42';
const FIXTURE_MATCH = '2026casf_qm42';
const CORRECTIONS_KEY = 'frc-scouting.fixture-corrections.v1';

async function loadJson<T>(name: string): Promise<T> {
  const url = `${FIXTURE_ROOT}/${name}`;
  const res = await fetch(url);
  if (!res.ok) throw new ApiError(`Fixture ${name} not found`, res.status, url);
  return (await res.json()) as T;
}

async function loadJsonl<T>(name: string): Promise<T[]> {
  const url = `${FIXTURE_ROOT}/${name}`;
  const res = await fetch(url);
  if (!res.ok) throw new ApiError(`Fixture ${name} not found`, res.status, url);
  const text = await res.text();
  return text
    .split('\n')
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as T);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Statuses a simulated job walks through, with how long it lingers in each. */
const PIPELINE: Array<[Job['status'], number]> = [
  ['queued', 1200],
  ['downloading', 4000],
  ['downloaded', 800],
  ['analyzing', 6000],
  ['complete', 0],
];

export class FixtureApi implements ScoutingApi {
  readonly mode = 'fixture' as const;

  private jobs: Job[] = [];
  private rawEvents: ScoutEvent[] | null = null;
  private tracks: Track[] | null = null;
  private corrections: Correction[] = [];
  private violations: ViolationLog = new ViolationLog();
  private seeded = false;
  private manualSeq = 0;

  // ---- loading

  private async seed(): Promise<void> {
    if (this.seeded) return;
    this.seeded = true;

    const [wireJob, wireEvents, wireTracks] = await Promise.all([
      loadJson<WireJob>('job.json'),
      loadJsonl<WireEvent>('events.jsonl'),
      loadJsonl<WireTrack>('tracks.jsonl'),
    ]);

    const log = new ViolationLog();
    const job = parseJob(wireJob, log);
    if (!job) throw new ApiError('Fixture job.json failed contract validation', 500, FIXTURE_ROOT);

    this.rawEvents = wireEvents
      .map((e) => parseEvent(e, log))
      .filter((e): e is ScoutEvent => e !== null)
      .sort((a, b) => a.tSeconds - b.tSeconds);
    this.tracks = wireTracks
      .map((t) => parseTrack(t, log))
      .filter((t): t is Track => t !== null);
    this.violations = log;

    // Corrections ship with the fixture; anything the user does this session stacks on top
    // and survives a refresh so a half-finished review is not lost.
    try {
      const wire = await loadJsonl<WireCorrection>('corrections.jsonl');
      this.corrections = wire
        .map((c) => parseCorrection(c, log))
        .filter((c): c is Correction => c !== null);
    } catch {
      this.corrections = [];
    }
    try {
      const saved = localStorage.getItem(CORRECTIONS_KEY);
      if (saved) this.corrections = [...this.corrections, ...(JSON.parse(saved) as Correction[])];
    } catch {
      // private window, or storage disabled -- session-only corrections are fine
    }

    // A queue with something in every interesting state, so the sidebar is not empty and
    // the retry path is reachable without waiting for a real failure.
    this.jobs = [
      job,
      {
        ...job,
        jobId: '7c19e5b2-4a3f-4d81-9e02-6b5c8f1a2d47',
        matchId: '2026casf_qm43',
        videoId: 'kJQP7kiw5Fk',
        status: 'analyzing',
        progress: 0.42,
        stage: 'tracking',
        tbaScore: null,
      },
      {
        ...job,
        jobId: 'b3f0a71c-9d24-4e6a-8c15-0f7b2e9d4a83',
        matchId: '2026casf_qm44',
        videoId: 'M7lc1UVf-VE',
        status: 'failed',
        error: 'yt-dlp: HTTP Error 403: Forbidden (format 137 unavailable, try updating yt-dlp)',
        tbaScore: null,
      },
      {
        ...job,
        jobId: 'd8e2c460-1b73-4f9a-a5d8-3c6e0b1f7a29',
        matchId: null,
        videoId: '9bZkp7q19f0',
        status: 'queued',
        tbaScore: null,
      },
    ];
  }

  private persist() {
    try {
      const shipped = 3; // the three that come from corrections.jsonl
      localStorage.setItem(CORRECTIONS_KEY, JSON.stringify(this.corrections.slice(shipped)));
    } catch {
      // non-fatal
    }
  }

  private async events(): Promise<ScoutEvent[]> {
    await this.seed();
    return this.rawEvents ?? [];
  }

  // ---- jobs

  async listJobs(): Promise<Parsed<Job[]>> {
    await this.seed();
    return { data: [...this.jobs], violations: this.violations.items };
  }

  async getJob(jobId: string): Promise<Parsed<Job | null>> {
    await this.seed();
    return { data: this.jobs.find((j) => j.jobId === jobId) ?? null, violations: [] };
  }

  async createJob(input: CreateJobInput): Promise<Parsed<Job>> {
    await this.seed();
    const template = this.jobs[0];
    const videoId = extractId(input.url) ?? 'dQw4w9WgXcQ';
    const job: Job = {
      ...template,
      jobId: uuid(),
      matchId: input.matchId ?? null,
      videoId,
      status: 'queued',
      progress: 0,
      stage: null,
      error: null,
      createdAt: new Date().toISOString(),
    };
    this.jobs = [job, ...this.jobs];
    void this.advance(job.jobId);
    return { data: job, violations: [] };
  }

  /** Walk a simulated job through the pipeline so the queue UI has something to show. */
  private async advance(jobId: string): Promise<void> {
    for (const [status, dwell] of PIPELINE) {
      await sleep(dwell);
      const i = this.jobs.findIndex((j) => j.jobId === jobId);
      if (i < 0) return; // deleted mid-flight
      const progress = status === 'analyzing' || status === 'downloading' ? 0 : null;
      this.jobs[i] = {
        ...this.jobs[i],
        status,
        progress,
        stage: status === 'analyzing' ? 'tracking' : status === 'downloading' ? 'yt-dlp' : null,
        // Only the fixture match has real data behind it.
        matchId: status === 'complete' ? (this.jobs[i].matchId ?? FIXTURE_MATCH) : this.jobs[i].matchId,
      };
      this.jobs = [...this.jobs];
    }
  }

  async deleteJob(jobId: string): Promise<void> {
    await this.seed();
    this.jobs = this.jobs.filter((j) => j.jobId !== jobId);
  }

  async retryJob(job: Job): Promise<Parsed<Job>> {
    return this.createJob({
      url: `https://www.youtube.com/watch?v=${job.videoId}`,
      matchId: job.matchId,
    });
  }

  // ---- match data

  async getEvents(matchId: string, query: EventQuery = {}): Promise<Parsed<ScoutEvent[]>> {
    const raw = await this.events();
    if (matchId !== FIXTURE_MATCH) return { data: [], violations: [] };
    const base = query.raw
      ? raw
      : (applyCorrections(raw, this.corrections) as ScoutEvent[]);
    const min = query.minConfidence ?? 0;
    return {
      data: base.filter((e) => e.confidence >= min),
      violations: this.violations.items,
    };
  }

  async getTracks(matchId: string): Promise<Parsed<Track[]>> {
    await this.seed();
    if (matchId !== FIXTURE_MATCH) return { data: [], violations: [] };
    return { data: this.tracks ?? [], violations: [] };
  }

  async getAccuracy(matchId: string): Promise<Accuracy> {
    const { data } = await this.getEvents(matchId, { raw: true });
    const job = this.jobs.find((j) => j.matchId === matchId) ?? this.jobs[0];
    const report = accuracyReport(data, job?.alliances ?? null, job?.tbaScore ?? null);
    return {
      matchId,
      reconstructed: report.reconstructed,
      tba: report.tba,
      delta: report.delta,
    };
  }

  async getCorrections(matchId: string): Promise<Parsed<Correction[]>> {
    await this.seed();
    if (matchId !== FIXTURE_MATCH) return { data: [], violations: [] };
    return { data: [...this.corrections], violations: [] };
  }

  // ---- corrections

  async createEvent(event: Omit<ScoutEvent, 'eventId'>): Promise<Parsed<ScoutEvent>> {
    await this.seed();
    const eventId = `${event.jobId.slice(0, 8)}-m${String(++this.manualSeq).padStart(3, '0')}`;
    const created: ScoutEvent = { ...event, eventId, source: 'manual' };
    this.corrections.push({
      correctionId: uuid(),
      eventId,
      action: 'create',
      fields: created,
      createdAt: new Date().toISOString(),
    });
    this.persist();
    const log = new ViolationLog();
    const parsed = parseEvent(eventToWire(created), log);
    if (!parsed) throw new ApiError('Manual event failed contract validation', 400, '/events');
    return { data: parsed, violations: log.items };
  }

  async patchEvent(eventId: string, fields: Partial<ScoutEvent>): Promise<Parsed<ScoutEvent>> {
    await this.seed();
    this.corrections.push({
      correctionId: uuid(),
      eventId,
      action: 'edit',
      fields,
      createdAt: new Date().toISOString(),
    });
    this.persist();
    const corrected = applyCorrections(this.rawEvents ?? [], this.corrections);
    const found = corrected.find((e) => e.eventId === eventId);
    if (!found) throw new ApiError(`No event ${eventId}`, 404, '/events');
    return { data: found, violations: [] };
  }

  async deleteEvent(eventId: string): Promise<void> {
    await this.seed();
    this.corrections.push({
      correctionId: uuid(),
      eventId,
      action: 'delete',
      fields: null,
      createdAt: new Date().toISOString(),
    });
    this.persist();
  }

  /** Drop every correction made in this browser. Fixture-only; there is no such API call. */
  async resetCorrections(): Promise<void> {
    await this.seed();
    this.corrections = this.corrections.slice(0, 3);
    try {
      localStorage.removeItem(CORRECTIONS_KEY);
    } catch {
      // non-fatal
    }
  }

  // ---- stats and export

  async getTeamStats(team: number, eventKey?: string): Promise<TeamStatsSummary> {
    const { data } = await this.getEvents(FIXTURE_MATCH);
    const job = this.jobs[0];
    const alliance = job?.alliances?.red.includes(team)
      ? ('red' as const)
      : job?.alliances?.blue.includes(team)
        ? ('blue' as const)
        : null;
    const s = computeTeamStats(team, data, alliance);
    return {
      team,
      eventKey: eventKey ?? null,
      matchesPlayed: 1,
      shotAttempts: s.shotAttempts,
      shotsMade: s.shotsMade,
      accuracy: s.accuracy,
      reloads: s.reloads,
      cycleCount: s.cycleCount,
      medianCycleSeconds: s.medianCycleSeconds,
      bestCycleSeconds: s.bestCycleSeconds,
      defenseSeconds: s.defenseSeconds,
      immobileSeconds: s.immobileSeconds,
      fouls: s.fouls,
      pointsContributed: s.pointsContributed,
    };
  }

  async exportSheets(input: ExportInput): Promise<ExportResult> {
    await this.seed();
    await sleep(700);
    const { data } = await this.getEvents(FIXTURE_MATCH);
    const teams = new Set(data.map((e) => e.team).filter((t): t is number => t != null));
    const rows = input.mode === 'raw' ? data.length : teams.size * input.matchIds.length;
    return {
      spreadsheetId: '1FIXTUREsheetIdNotARealSpreadsheet',
      spreadsheetUrl: 'https://docs.google.com/spreadsheets/d/1FIXTUREsheetIdNotARealSpreadsheet',
      rowsWritten: rows,
      // Doc 3 wants re-export idempotent: a second run updates rather than appends.
      rowsUpdated: 0,
      mode: input.mode,
    };
  }

  videoUrl(_job: Job): string {
    return `${FIXTURE_ROOT}/segment.mp4`;
  }
}

function uuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function extractId(url: string): string | null {
  const m = url.match(/[?&]v=([A-Za-z0-9_-]{11})|youtu\.be\/([A-Za-z0-9_-]{11})/);
  return m ? (m[1] ?? m[2]) : /^[A-Za-z0-9_-]{11}$/.test(url.trim()) ? url.trim() : null;
}
