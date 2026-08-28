import { useMemo, useState } from 'react';
import { EVENT_TYPES, type EventType, type Job, type ScoutEvent } from '../contracts';
import type { ViewEvent } from '../lib/corrections';
import { EVENT_LABEL, PHASE_LABEL, SOURCE_LABEL, fmtTime } from '../lib/format';

// Doc 3: "Build this early. Users will find wrong calls, and a tool that cannot be corrected
// will not be trusted." And: "Minimum useful version: scrub to an event, see what the
// pipeline claimed, fix the team attribution or delete the event, add a missed one."
//
// Every action here writes a correction row. Nothing overwrites model output.

export interface EventInspectorProps {
  job: Job;
  events: ViewEvent[];
  deleted: ScoutEvent[];
  currentTime: number;
  confidenceThreshold: number;
  onConfidenceThreshold: (v: number) => void;
  selectedEventId: string | null;
  onSelectEvent: (id: string | null) => void;
  onSeek: (t: number) => void;
  onPatch: (eventId: string, fields: Partial<ScoutEvent>) => Promise<void>;
  onDelete: (eventId: string) => Promise<void>;
  onCreate: (event: Omit<ScoutEvent, 'eventId'>) => Promise<void>;
}

export function EventInspector(props: EventInspectorProps) {
  const {
    job,
    events,
    deleted,
    currentTime,
    confidenceThreshold,
    onConfidenceThreshold,
    selectedEventId,
    onSelectEvent,
    onSeek,
    onPatch,
    onDelete,
    onCreate,
  } = props;

  const [teamFilter, setTeamFilter] = useState<number | 'all' | 'none'>('all');
  const [typeFilter, setTypeFilter] = useState<EventType | 'all'>('all');
  const [onlyLow, setOnlyLow] = useState(false);
  const [onlyCorrected, setOnlyCorrected] = useState(false);
  const [busy, setBusy] = useState(false);

  const allTeams = useMemo(
    () => [...(job.alliances?.red ?? []), ...(job.alliances?.blue ?? [])],
    [job.alliances]
  );

  const shown = useMemo(
    () =>
      events.filter((e) => {
        if (onlyLow && e.confidence >= confidenceThreshold) return false;
        if (onlyCorrected && !e.correctionState) return false;
        if (typeFilter !== 'all' && e.eventType !== typeFilter) return false;
        if (teamFilter === 'none' && e.team != null) return false;
        if (typeof teamFilter === 'number' && e.team !== teamFilter) return false;
        return true;
      }),
    [events, onlyLow, onlyCorrected, typeFilter, teamFilter, confidenceThreshold]
  );

  const lowCount = events.filter((e) => e.confidence < confidenceThreshold).length;
  const selected = events.find((e) => e.eventId === selectedEventId) ?? null;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel inspector">
      <div className="panel-head">
        <h2>Events &amp; corrections</h2>
        <span className="muted">
          {shown.length} of {events.length} · {lowCount} below threshold
        </span>
      </div>

      {/* Doc 3: "Surface it, and let users filter the view by threshold." */}
      <div className="filters">
        <label className="filter conf">
          Confidence ≥ <strong>{confidenceThreshold.toFixed(2)}</strong>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={confidenceThreshold}
            onChange={(e) => onConfidenceThreshold(Number(e.target.value))}
          />
        </label>
        <label className="filter">
          Team
          <select
            value={String(teamFilter)}
            onChange={(e) => {
              const v = e.target.value;
              setTeamFilter(v === 'all' || v === 'none' ? v : Number(v));
            }}
          >
            <option value="all">all</option>
            {allTeams.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
            <option value="none">unattributed</option>
          </select>
        </label>
        <label className="filter">
          Type
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as EventType | 'all')}
          >
            <option value="all">all</option>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>{EVENT_LABEL[t]}</option>
            ))}
          </select>
        </label>
        <label className="filter check">
          <input type="checkbox" checked={onlyLow} onChange={(e) => setOnlyLow(e.target.checked)} />
          Low confidence only
        </label>
        <label className="filter check">
          <input
            type="checkbox"
            checked={onlyCorrected}
            onChange={(e) => setOnlyCorrected(e.target.checked)}
          />
          Corrected only
        </label>
      </div>

      <AddEventRow
        job={job}
        currentTime={currentTime}
        teams={allTeams}
        busy={busy}
        onCreate={(e) => run(() => onCreate(e))}
      />

      <div className="event-list">
        {shown.length === 0 && <p className="empty">Nothing matches these filters.</p>}
        {shown.map((e) => (
          <EventRow
            key={e.eventId}
            e={e}
            low={e.confidence < confidenceThreshold}
            selected={e.eventId === selectedEventId}
            onClick={() => {
              onSelectEvent(e.eventId === selectedEventId ? null : e.eventId);
              onSeek(e.tSeconds);
            }}
          />
        ))}
      </div>

      {selected && (
        <EditPanel
          e={selected}
          teams={allTeams}
          busy={busy}
          onPatch={(fields) => run(() => onPatch(selected.eventId, fields))}
          onDelete={() => run(() => onDelete(selected.eventId))}
          onSeek={() => onSeek(selected.tSeconds)}
        />
      )}

      {deleted.length > 0 && (
        <details className="deleted">
          <summary>{deleted.length} deleted by a reviewer</summary>
          <p className="note">
            Still in the raw event table — a delete is a correction row, not a removal, so
            these remain available for model evaluation and training export.
          </p>
          <ul>
            {deleted.map((e) => (
              <li key={e.eventId}>
                <button type="button" className="linky" onClick={() => onSeek(e.tSeconds)}>
                  {fmtTime(e.tSeconds)}
                </button>{' '}
                {EVENT_LABEL[e.eventType]} · {e.team ?? 'unattributed'} · conf{' '}
                {e.confidence.toFixed(2)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function EventRow({
  e,
  low,
  selected,
  onClick,
}: {
  e: ViewEvent;
  low: boolean;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`event-row ${low ? 'low' : ''} ${selected ? 'sel' : ''} ${
        e.correctionState ?? ''
      }`}
      onClick={onClick}
    >
      <span className="t">{fmtTime(e.tSeconds)}</span>
      <span className={`team ${e.team == null ? 'none' : ''}`}>
        {e.team ?? (e.trackId != null ? `tr${e.trackId}` : '--')}
      </span>
      <span className="type">{EVENT_LABEL[e.eventType]}</span>
      <span className="phase">{PHASE_LABEL[e.phase]}</span>
      <span className="conf" title={`confidence ${e.confidence}`}>
        <span className="conf-bar" style={{ width: `${e.confidence * 100}%` }} />
        <span className="conf-num">{e.confidence.toFixed(2)}</span>
      </span>
      {e.correctionState && <span className={`tag ${e.correctionState}`}>{e.correctionState}</span>}
      {e.source !== 'model' && !e.correctionState && (
        <span className="tag src">{SOURCE_LABEL[e.source]}</span>
      )}
    </button>
  );
}

function EditPanel({
  e,
  teams,
  busy,
  onPatch,
  onDelete,
  onSeek,
}: {
  e: ViewEvent;
  teams: number[];
  busy: boolean;
  onPatch: (fields: Partial<ScoutEvent>) => void;
  onDelete: () => void;
  onSeek: () => void;
}) {
  return (
    <div className="edit-panel">
      <div className="edit-head">
        <strong>{EVENT_LABEL[e.eventType]}</strong>
        <button type="button" className="linky" onClick={onSeek}>
          {fmtTime(e.tSeconds)}
        </button>
        <code className="muted">{e.eventId}</code>
      </div>

      {e.correctionState === 'edited' && e.original && (
        <p className="note was">
          Model originally said:{' '}
          <strong>{e.original.team ?? 'unattributed'}</strong> ·{' '}
          {EVENT_LABEL[e.original.eventType]} · conf {e.original.confidence.toFixed(2)}
        </p>
      )}

      <div className="edit-grid">
        <label>
          Team
          <select
            disabled={busy}
            value={e.team ?? ''}
            onChange={(ev) => onPatch({ team: ev.target.value ? Number(ev.target.value) : null })}
          >
            <option value="">unattributed</option>
            {teams.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </label>

        <label>
          Event type
          <select
            disabled={busy}
            value={e.eventType}
            onChange={(ev) => onPatch({ eventType: ev.target.value as EventType })}
          >
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>{EVENT_LABEL[t]}</option>
            ))}
          </select>
        </label>

        <div className="edit-meta">
          <span>track {e.trackId ?? '--'}</span>
          <span>{PHASE_LABEL[e.phase]}</span>
          <span>{SOURCE_LABEL[e.source]}</span>
          <span>
            field{' '}
            {e.fieldX != null && e.fieldY != null
              ? `${e.fieldX.toFixed(1)}, ${e.fieldY.toFixed(1)} ft`
              : 'no homography'}
          </span>
        </div>
      </div>

      <div className="edit-actions">
        <button type="button" className="danger" disabled={busy} onClick={onDelete}>
          Delete event
        </button>
        <span className="note">
          Writes a correction row. The raw event stays in the table for evaluation.
        </span>
      </div>

      <p className="note warn-note">
        Team attribution really belongs to the track, not one event — correcting it here fixes
        this row only, and the overlay box keeps the old label. See OPEN_QUESTIONS.md #10.
      </p>
    </div>
  );
}

function AddEventRow({
  job,
  currentTime,
  teams,
  busy,
  onCreate,
}: {
  job: Job;
  currentTime: number;
  teams: number[];
  busy: boolean;
  onCreate: (e: Omit<ScoutEvent, 'eventId'>) => void;
}) {
  const [team, setTeam] = useState<number | ''>(teams[0] ?? '');
  const [type, setType] = useState<EventType>('shot_made');

  const phaseAt = (t: number) =>
    t < 15 ? ('auto' as const) : t < 130 ? ('teleop' as const) : ('endgame' as const);

  return (
    <div className="add-row">
      <span className="add-label">Add missed event at {fmtTime(currentTime)}</span>
      <select value={team} onChange={(e) => setTeam(e.target.value ? Number(e.target.value) : '')}>
        {teams.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>
      <select value={type} onChange={(e) => setType(e.target.value as EventType)}>
        {EVENT_TYPES.map((t) => (
          <option key={t} value={t}>{EVENT_LABEL[t]}</option>
        ))}
      </select>
      <button
        type="button"
        disabled={busy || team === ''}
        onClick={() =>
          onCreate({
            jobId: job.jobId,
            matchId: job.matchId ?? '',
            team: team === '' ? null : team,
            trackId: null,
            tSeconds: Math.round(currentTime * 1000) / 1000,
            phase: phaseAt(currentTime),
            eventType: type,
            confidence: 1,
            fieldX: null,
            fieldY: null,
            source: 'manual',
          })
        }
      >
        Add
      </button>
    </div>
  );
}
