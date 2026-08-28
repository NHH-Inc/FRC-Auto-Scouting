// The corrections layer.
//
// Doc 0: "Corrections never overwrite model output. A correction is a new row referencing
// the original... Keeping both is the whole point: overwriting destroys the ability to
// measure whether the model is improving."
//
// So the UI holds raw events and corrections separately and composes them here. Nothing in
// web/ ever mutates a raw event in place.

import type { Correction, ScoutEvent } from '../contracts';

export type CorrectionState = 'edited' | 'created' | null;

export interface ViewEvent extends ScoutEvent {
  /** How this row came to look the way it does. null means untouched model output. */
  correctionState: CorrectionState;
  /** The uncorrected event, present when correctionState is 'edited'. */
  original: ScoutEvent | null;
  /** Which fields a correction changed, for highlighting in the inspector. */
  changedFields: ReadonlyArray<keyof ScoutEvent>;
}

const asView = (e: ScoutEvent): ViewEvent => ({
  ...e,
  correctionState: null,
  original: null,
  changedFields: [],
});

/**
 * Apply corrections on top of raw events, which is what doc 0 says reads do by default.
 * Deleted events drop out; edited events keep a pointer to the original; created events are
 * appended with source 'manual'.
 */
export function applyCorrections(raw: ScoutEvent[], corrections: Correction[]): ViewEvent[] {
  const byId = new Map<string, ViewEvent>();
  for (const e of raw) byId.set(e.eventId, asView(e));
  const deleted = new Set<string>();

  // Oldest first, so a later correction to the same event wins.
  const ordered = [...corrections].sort((a, b) => a.createdAt.localeCompare(b.createdAt));

  for (const c of ordered) {
    if (c.action === 'delete') {
      deleted.add(c.eventId);
      continue;
    }
    if (c.action === 'create') {
      const f = c.fields ?? {};
      byId.set(c.eventId, {
        ...asView({
          jobId: f.jobId ?? '',
          matchId: f.matchId ?? '',
          eventId: c.eventId,
          team: f.team ?? null,
          trackId: f.trackId ?? null,
          tSeconds: f.tSeconds ?? 0,
          phase: f.phase ?? 'unknown',
          eventType: f.eventType ?? 'shot_attempt',
          confidence: f.confidence ?? 1,
          fieldX: f.fieldX ?? null,
          fieldY: f.fieldY ?? null,
          source: 'manual',
        }),
        correctionState: 'created',
      });
      deleted.delete(c.eventId);
      continue;
    }
    // edit
    const target = byId.get(c.eventId);
    if (!target || !c.fields) continue;
    const changed = (Object.keys(c.fields) as Array<keyof ScoutEvent>).filter(
      (k) => c.fields![k] !== target[k]
    );
    byId.set(c.eventId, {
      ...target,
      ...c.fields,
      correctionState: 'edited',
      original: target.original ?? (target as ScoutEvent),
      changedFields: [...new Set([...target.changedFields, ...changed])],
    });
  }

  return [...byId.values()]
    .filter((e) => !deleted.has(e.eventId))
    .sort((a, b) => a.tSeconds - b.tSeconds);
}

/**
 * Recover correction state by diffing raw against corrected.
 *
 * Needed only because Contract E has no endpoint that lists corrections
 * (OPEN_QUESTIONS.md #3). Two requests where one would do, and `createdAt` is
 * unrecoverable -- delete this the day that endpoint exists.
 */
export function deriveCorrectionState(raw: ScoutEvent[], corrected: ScoutEvent[]): ViewEvent[] {
  const rawById = new Map(raw.map((e) => [e.eventId, e]));
  return corrected
    .map((e) => {
      const before = rawById.get(e.eventId);
      if (!before) return { ...asView(e), correctionState: 'created' as const };
      const changed = (Object.keys(e) as Array<keyof ScoutEvent>).filter(
        (k) => e[k] !== before[k]
      );
      if (changed.length === 0) return asView(e);
      return {
        ...asView(e),
        correctionState: 'edited' as const,
        original: before,
        changedFields: changed,
      };
    })
    .sort((a, b) => a.tSeconds - b.tSeconds);
}

/** Events present in raw but absent from the corrected view -- i.e. deleted by a human. */
export function deletedEvents(raw: ScoutEvent[], corrected: ScoutEvent[]): ScoutEvent[] {
  const keep = new Set(corrected.map((e) => e.eventId));
  return raw.filter((e) => !keep.has(e.eventId));
}
