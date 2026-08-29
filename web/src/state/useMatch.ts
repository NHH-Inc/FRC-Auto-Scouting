import { useCallback, useEffect, useState } from 'react';
import { getApi } from '../api';
import type { Accuracy } from '../api/shapes';
import type { ContractViolation, Correction, ScoutEvent, Track } from '../contracts';
import { deletedEvents, toViewEvents, type ViewEvent } from '../lib/corrections';

export interface MatchData {
  /** Uncorrected model output. The accuracy comparison and any training export use this. */
  raw: ScoutEvent[];
  /** Corrected view, paired against raw so the inspector can show the original. */
  events: ViewEvent[];
  /** Raw events a human deleted. Kept so the inspector can offer to undo. */
  deleted: ScoutEvent[];
  tracks: Track[];
  corrections: Correction[];
  accuracy: Accuracy | null;
  /** Contract C, served on the tracks response in v2 rather than inferred. */
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
  corrections: [],
  accuracy: null,
  boxSampleRate: 0,
  loading: true,
  error: null,
  violations: [],
};

/**
 * Everything the analysis view needs for one match.
 *
 * Fetches raw and corrected separately: doc 0 keeps corrections as their own layer, and the
 * UI wants both -- corrected to display, raw so the inspector can show what the model
 * originally said. Which rows a human touched now comes from the API's `corrected` flag, not
 * from a client-side diff.
 */
export function useMatch(matchId: string | null, ready = true) {
  const [data, setData] = useState<MatchData>(EMPTY);

  const load = useCallback(async () => {
    if (!matchId || !ready) {
      setData({ ...EMPTY, loading: false });
      return;
    }
    setData((d) => ({ ...d, loading: true, error: null }));
    try {
      const api = await getApi();
      const [rawRes, corrRes, tracksRes, correctionsRes] = await Promise.all([
        api.getEvents(matchId, { raw: true }),
        api.getEvents(matchId),
        api.getTracks(matchId),
        api.getCorrections(matchId),
      ]);

      let accuracy: Accuracy | null = null;
      try {
        accuracy = await api.getAccuracy(matchId);
      } catch {
        // A match with no TBA data is not an error worth blocking the view on.
      }

      setData({
        raw: rawRes.data,
        events: toViewEvents(corrRes.data, rawRes.data),
        deleted: deletedEvents(rawRes.data, corrRes.data),
        tracks: tracksRes.data.tracks,
        corrections: correctionsRes.data,
        accuracy,
        boxSampleRate: tracksRes.data.boxSampleRate,
        loading: false,
        error: null,
        violations: [
          ...rawRes.violations,
          ...corrRes.violations,
          ...tracksRes.violations,
          ...correctionsRes.violations,
        ],
      });
    } catch (e) {
      setData({ ...EMPTY, loading: false, error: (e as Error).message });
    }
  }, [matchId, ready]);

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
    async (event: Omit<ScoutEvent, 'eventId' | 'corrected' | 'correctionId'>) => {
      const api = await getApi();
      await api.createEvent(event);
      await load();
    },
    [load]
  );

  /** Doc 3's primary correction path: re-attributes the track and every event on it. */
  const patchTrack = useCallback(
    async (jobId: string, trackId: number, team: number | null) => {
      const api = await getApi();
      await api.patchTrack(jobId, trackId, { team });
      await load();
    },
    [load]
  );

  const undoCorrection = useCallback(
    async (correctionId: string) => {
      const api = await getApi();
      await api.deleteCorrection(correctionId);
      await load();
    },
    [load]
  );

  return { ...data, reload: load, patchEvent, removeEvent, addEvent, patchTrack, undoCorrection };
}
