import { useCallback, useEffect, useState } from 'react';
import { getApi } from '../api';
import type { Accuracy } from '../api/shapes';
import type { ContractViolation, ScoutEvent, Track } from '../contracts';
import {
  applyCorrections,
  deriveCorrectionState,
  deletedEvents,
  type ViewEvent,
} from '../lib/corrections';
import { estimateSampleRate } from '../lib/tracks';

export interface MatchData {
  /** Uncorrected model output. The accuracy comparison and any training export use this. */
  raw: ScoutEvent[];
  /** Raw with the corrections layer applied -- what the UI shows by default. */
  events: ViewEvent[];
  /** Raw events a human deleted. Kept so the inspector can offer to undo. */
  deleted: ScoutEvent[];
  tracks: Track[];
  accuracy: Accuracy | null;
  boxSampleRate: number;
  loading: boolean;
  error: string | null;
  violations: ContractViolation[];
}

const EMPTY: MatchData = {
  raw: [],
  events: [],
  deleted: [],
  tracks: [],
  accuracy: null,
  boxSampleRate: 5,
  loading: true,
  error: null,
  violations: [],
};

/**
 * Everything the analysis view needs for one match.
 *
 * Fetches raw and corrected separately: doc 0 keeps corrections as their own layer, and the
 * UI wants both -- corrected to display, raw to diff against so it can mark which rows a
 * human touched. When component 2 grows a corrections endpoint (OPEN_QUESTIONS.md #3) the
 * diff path here can go away.
 */
export function useMatch(matchId: string | null) {
  const [data, setData] = useState<MatchData>(EMPTY);

  const load = useCallback(async () => {
    if (!matchId) {
      setData({ ...EMPTY, loading: false });
      return;
    }
    setData((d) => ({ ...d, loading: true, error: null }));
    try {
      const api = await getApi();
      const [rawRes, corrRes, tracksRes, corrections] = await Promise.all([
        api.getEvents(matchId, { raw: true }),
        api.getEvents(matchId),
        api.getTracks(matchId),
        api.getCorrections(matchId),
      ]);

      // Prefer real correction records when the API can give them; fall back to diffing.
      const events = corrections
        ? applyCorrections(rawRes.data, corrections.data)
        : deriveCorrectionState(rawRes.data, corrRes.data);

      let accuracy: Accuracy | null = null;
      try {
        accuracy = await api.getAccuracy(matchId);
      } catch {
        // Accuracy needs a TBA score; a match without one is not an error worth blocking on.
      }

      setData({
        raw: rawRes.data,
        events,
        deleted: deletedEvents(rawRes.data, events),
        tracks: tracksRes.data,
        accuracy,
        boxSampleRate: estimateSampleRate(tracksRes.data),
        loading: false,
        error: null,
        violations: [
          ...rawRes.violations,
          ...corrRes.violations,
          ...tracksRes.violations,
        ],
      });
    } catch (e) {
      setData({ ...EMPTY, loading: false, error: (e as Error).message });
    }
  }, [matchId]);

  useEffect(() => {
    void load();
  }, [load]);

  const patchEvent = useCallback(
    async (eventId: string, fields: Partial<ScoutEvent>) => {
      const api = await getApi();
      await api.patchEvent(eventId, fields);
      await load();
    },
    [load]
  );

  const removeEvent = useCallback(
    async (eventId: string) => {
      const api = await getApi();
      await api.deleteEvent(eventId);
      await load();
    },
    [load]
  );

  const addEvent = useCallback(
    async (event: Omit<ScoutEvent, 'eventId'>) => {
      const api = await getApi();
      await api.createEvent(event);
      await load();
    },
    [load]
  );

  return { ...data, reload: load, patchEvent, removeEvent, addEvent };
}
