// The corrections layer.
//
// Doc 0: "Corrections never overwrite model output... Keeping both is the whole point:
// overwriting destroys the ability to measure whether the model is improving."
//
// v2 moved correction *state* onto the API response: every returned event carries `corrected`
// and `correction_id`, so the client-side diff that used to reconstruct it is gone. What
// remains is pairing the corrected view against raw so the inspector can still show what the
// model originally said, and applying corrections locally in fixture mode.

import type { Correction, ScoutEvent } from '../contracts';

export interface ViewEvent extends ScoutEvent {
  /** The uncorrected event, when this row was edited. Null for untouched or created rows. */
  original: ScoutEvent | null;
  /** Which fields differ from the model's original, for highlighting. */
  changedFields: ReadonlyArray<keyof ScoutEvent>;
}

const NEVER_COMPARE: ReadonlySet<string> = new Set(['corrected', 'correctionId']);

/**
 * Pair the corrected stream against raw. `corrected` comes from the API, not from this diff --
 * the diff only recovers the before-values for display.
 */
export function toViewEvents(corrected: ScoutEvent[], raw: ScoutEvent[]): ViewEvent[] {
  const rawById = new Map(raw.map((e) => [e.eventId, e]));
  return corrected
    .map((e) => {
      const before = rawById.get(e.eventId);
      if (!before) {
        // Present in the corrected view but not in raw: a human created it.
        return { ...e, original: null, changedFields: [] };
      }
      const changed = (Object.keys(e) as Array<keyof ScoutEvent>).filter(
        (k) => !NEVER_COMPARE.has(k as string) && e[k] !== before[k]
      );
      return { ...e, original: changed.length ? before : null, changedFields: changed };
    })
    .sort((a, b) => a.tSeconds - b.tSeconds);
}

/** Events present in raw but absent from the corrected view -- i.e. deleted by a human. */
export function deletedEvents(raw: ScoutEvent[], corrected: ScoutEvent[]): ScoutEvent[] {
  const keep = new Set(corrected.map((e) => e.eventId));
  return raw.filter((e) => !keep.has(e.eventId));
}

/**
 * Compose corrections onto raw events. Only the fixture client needs this -- against a real
 * backend, component 2 does it and `raw=true` returns the uncorrected stream.
 *
 * A track-scoped correction re-attributes the track and EVERY event on it, as one action.
 * Doc 3: that is the primary correction path, because one bad OCR read mislabels forty-odd
 * events and every box on that robot.
 */
export function applyCorrections(
  raw: ScoutEvent[],
  corrections: Correction[]
): ScoutEvent[] {
  const byId = new Map<string, ScoutEvent>(raw.map((e) => [e.eventId, { ...e }]));
  const deleted = new Set<string>();

  // Oldest first, so a later correction to the same target wins.
  const ordered = [...corrections].sort((a, b) => a.createdAt.localeCompare(b.createdAt));

  for (const c of ordered) {
    if (c.scope === 'track') {
      const trackId = Number(c.targetId);
      for (const [id, e] of byId) {
        if (e.trackId !== trackId) continue;
        byId.set(id, { ...e, ...c.fields, corrected: true, correctionId: c.correctionId });
      }
      continue;
    }

    if (c.action === 'delete') {
      deleted.add(c.targetId);
      continue;
    }

    if (c.action === 'create') {
      const f = c.fields ?? {};
      byId.set(c.targetId, {
        jobId: f.jobId ?? '',
        matchId: f.matchId ?? '',
        eventId: c.targetId,
        team: f.team ?? null,
        trackId: f.trackId ?? null,
        tSeconds: f.tSeconds ?? 0,
        phase: f.phase ?? 'unknown',
        eventType: f.eventType ?? 'shot_attempt',
        confidence: f.confidence ?? 1,
        fieldX: f.fieldX ?? null,
        fieldY: f.fieldY ?? null,
        goal: f.goal ?? null,
        source: 'manual',
        corrected: true,
        correctionId: c.correctionId,
      });
      deleted.delete(c.targetId);
      continue;
    }

    const target = byId.get(c.targetId);
    if (!target || !c.fields) continue;
    byId.set(c.targetId, {
      ...target,
      ...c.fields,
      corrected: true,
      correctionId: c.correctionId,
    });
  }

  return [...byId.entries()]
    .filter(([id]) => !deleted.has(id))
    .map(([, e]) => e)
    .sort((a, b) => a.tSeconds - b.tSeconds);
}

/** Apply track-scoped corrections to the tracks themselves, so the overlay labels follow. */
export function applyTrackCorrections<T extends { trackId: number; team: number | null }>(
  tracks: T[],
  corrections: Correction[]
): T[] {
  const byTrack = new Map<number, Partial<{ team: number | null }>>();
  for (const c of [...corrections].sort((a, b) => a.createdAt.localeCompare(b.createdAt))) {
    if (c.scope !== 'track' || !c.fields) continue;
    byTrack.set(Number(c.targetId), { team: c.fields.team ?? null });
  }
  return tracks.map((t) => {
    const patch = byTrack.get(t.trackId);
    return patch ? { ...t, ...patch } : t;
  });
}
