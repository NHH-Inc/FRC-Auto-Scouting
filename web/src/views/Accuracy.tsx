import type { Accuracy as AccuracyData } from '../api/shapes';
import { fmtSigned } from '../lib/format';

// Doc 3: "Reconstructed score vs. TBA official score, as a visible accuracy indicator per
// match." Doc 1 is blunter: "If the pipeline's reconstructed score does not match TBA's
// official score for the same match, the pipeline is wrong. That comparison is the main
// evaluation loop."
//
// So this panel reads from RAW model output, not the corrected view. Scoring a corrected
// event stream against TBA would measure the humans, not the model, and the number would
// improve every time somebody fixed a row by hand.

export interface AccuracyPanelProps {
  accuracy: AccuracyData | null;
  /** True when the numbers came from raw, uncorrected events. */
  fromRaw: boolean;
}

export function AccuracyPanel({ accuracy, fromRaw }: AccuracyPanelProps) {
  if (!accuracy) {
    return (
      <div className="panel">
        <div className="panel-head"><h2>Score accuracy</h2></div>
        <p className="empty">No accuracy data. This needs a TBA score for the match.</p>
      </div>
    );
  }

  const { reconstructed, tba, delta } = accuracy;
  const mae = delta ? (Math.abs(delta.red) + Math.abs(delta.blue)) / 2 : null;
  const grade = mae == null ? null : mae <= 3 ? 'good' : mae <= 10 ? 'fair' : 'bad';

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Score accuracy</h2>
        <span className="muted">reconstructed vs TBA official</span>
      </div>

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
          {delta ? fmtSigned(delta.red) : '--'}
        </div>
        <div className={`acc-val delta ${delta && delta.blue !== 0 ? 'off' : ''}`}>
          {delta ? fmtSigned(delta.blue) : '--'}
        </div>
      </div>

      {mae != null && (
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
        {' '}Point values come from the season config, which is a placeholder until the 2026
        game is public.
      </p>
    </div>
  );
}
