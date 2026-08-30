import { useCallback, useEffect, useState } from 'react';
import { getApi } from '../api';
import type { RunResult } from '../api/shapes';

export interface RunResultState {
  result: RunResult | null;
  loading: boolean;
  error: string | null;
}

const EMPTY: RunResultState = { result: null, loading: false, error: null };

/** Fetch Contract D's result.json separately from events/tracks.

It lets a reviewer distinguish "the detector found no robots" from "no detector was configured"
without guessing from an empty overlay.
 */
export function useRunResult(jobId: string | null, ready: boolean) {
  const [state, setState] = useState<RunResultState>(EMPTY);

  const load = useCallback(async () => {
    if (!jobId || !ready) {
      setState(EMPTY);
      return;
    }
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const api = await getApi();
      const result = await api.getResult(jobId);
      setState({ result, loading: false, error: null });
    } catch (error) {
      setState({ result: null, loading: false, error: (error as Error).message });
    }
  }, [jobId, ready]);

  useEffect(() => {
    void load();
  }, [load]);

  return { ...state, reload: load };
}
