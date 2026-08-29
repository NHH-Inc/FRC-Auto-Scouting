import type { Accuracy as AccuracyData } from '../api/shapes';
import { fmtSigned } from '../lib/format';
import { pointValuesArePlaceholders, type SeasonConfig } from '../season';

// Doc 3: "Reconstructed score vs. TBA official score, as a visible accuracy indicator per
// match." Doc 1 is blunter: "If the pipeline's reconstructed score does not match TBA's
// official score for the same match, the pipeline is wrong. That comparison is the main
// evaluation loop."
//
// Scored from RAW model output, never the corrected stream -- that would measure the
// reviewers, and the number would improve every time somebody fixed a row by hand.

export interface AccuracyPanelProps {
  accuracy: AccuracyData | null;
  season: SeasonConfig | null;
  /** True when the numbers came from raw, uncorrected events. */
  fromRaw: boolean;
}

export function AccuracyPanel({ accuracy, season, fromRaw }: AccuracyPanelProps) {
  if (!accuracy) {
    return (
      <div className="panel">
        <div className="panel-head"><h2>Score accuracy</h2></div>
        <p className="empty">No accuracy data for this match.</p>
      </div>
    );
  }

  const placeholders = season == null || pointValuesArePlaceholders(season);
  const { reconstructed, tba, delta, tbaAvailable } = accuracy;
  const mae = delta ? (Math.abs(delta.red) + Math.abs(delta.blue)) / 2 : null;
  const grade = mae == null ? null : mae <= 3 ? 'good' : mae <= 10 ? 'fair' : 'bad';

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Score accuracy</h2>
        <span className="muted">reconstructed vs TBA official</span>
      </div>

      {/* Doc 0: "Point values are zero placeholders until the game is public. Score
          reconstruction is not meaningful until they are filled in, and that is expected."
          Showing a confident delta against an all-zero scoring model would be a lie. */}
      {placeholders && (
        <div className="acc-verdict fair">
          <strong>Not meaningful yet.</strong>
          <span className="muted">
            {' '}
            Every point value in{' '}
            <code>contracts/seasons/{season?.season ?? '<year>'}.json</code> is still a zero
            placeholder, so the reconstruction below is zero by construction — not a pipeline
            failure. Fill the values in once the game is public.
          </span>
        </div>
      )}

      {!tbaAvailable && (
        <div className="acc-verdict fair">
          <strong>No TBA data for this match.</strong>
          <span className="muted">
            {' '}
            There is nothing to compare against — which is different from a reconstruction that
            matched.
          </span>
        </div>
      )}

      <div className="acc-grid">
        <div />
        <div className="acc-col red">Red</div>
        <div className="acc-col blue">Blue</div>

        <div className="acc-row">Reconstructed</div>
        <div className="acc-val">{reconstructed.red}</div>
        <div className="acc-val">{reconstructed.blue}</div>

        <div className="acc-row">TBA official</div>
        <div className="acc-val">{tba ? tba.red : '--'}</div>
        <div className="acc-val">{tba ? tba.blue : '--'}</div>

        <div className="acc-row">Delta</div>
        <div className={`acc-val delta ${delta && delta.red !== 0 ? 'off' : ''}`}>
          {delta && !placeholders ? fmtSigned(delta.red) : '--'}
        </div>
        <div className={`acc-val delta ${delta && delta.blue !== 0 ? 'off' : ''}`}>
          {delta && !placeholders ? fmtSigned(delta.blue) : '--'}
        </div>
      </div>

      {mae != null && !placeholders && (
        <div className={`acc-verdict ${grade}`}>
          <strong>{mae.toFixed(1)} pts</strong> mean absolute error
          <span className="muted">
            {grade === 'good'
              ? ' — reconstruction tracks the official score'
              : grade === 'fair'
                ? ' — close, but events are being missed or double-counted'
                : ' — the pipeline is wrong for this match; do not trust its per-robot numbers'}
          </span>
        </div>
      )}

      <p className="note">
        Computed from {fromRaw ? 'raw model output' : 'corrected events'}
        {fromRaw
          ? '. Corrections are deliberately excluded — scoring the corrected stream would measure the reviewers, not the model.'
          : '. Warning: this includes human corrections, so it flatters the model.'}
      </p>
    </div>
  );
}
