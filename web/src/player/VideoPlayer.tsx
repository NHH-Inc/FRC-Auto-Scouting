import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PlayableJob, Track } from '../contracts';
import type { ViewEvent } from '../lib/corrections';
import { EVENT_LABEL, fmtClock, fmtTime, youtubeUrlAt } from '../lib/format';
import { visibleBoxes } from '../lib/tracks';
import { PHASE_BOUNDS } from '../season';

// requestVideoFrameCallback is what makes the overlay frame-accurate instead of merely
// close. lib.dom declares it, but not every browser implements it (Firefox), so it is
// feature-detected rather than assumed.
interface FrameMeta {
  mediaTime: number;
  presentedFrames: number;
}
interface RVFCCapable {
  requestVideoFrameCallback(cb: (now: number, meta: FrameMeta) => void): number;
  cancelVideoFrameCallback(handle: number): void;
}

const RED = '#e0555f';
const BLUE = '#4c8cf0';
const GREY = '#8a8f9c';
const LOW_CONF = '#e8b93b';

export interface VideoPlayerProps {
  job: PlayableJob;
  src: string;
  tracks: Track[];
  events: ViewEvent[];
  /** Events below this are drawn as suspect. Doc 3: low confidence must be visually distinct. */
  confidenceThreshold: number;
  boxSampleRate: number;
  selectedEventId: string | null;
  onSelectEvent: (eventId: string | null) => void;
  /** Set by the parent when the user scrubs to an event from elsewhere in the UI. */
  seekTo: { t: number; nonce: number } | null;
  onTimeChange?: (t: number) => void;
}

export function VideoPlayer({
  job,
  src,
  tracks,
  events,
  confidenceThreshold,
  boxSampleRate,
  selectedEventId,
  onSelectEvent,
  seekTo,
  onTimeChange,
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [showBoxes, setShowBoxes] = useState(true);
  const [ready, setReady] = useState(false);

  // The overlay redraws from whatever these hold, so the frame callback never re-subscribes.
  const drawState = useRef({ tracks, events, confidenceThreshold, showBoxes, boxSampleRate });
  drawState.current = { tracks, events, confidenceThreshold, showBoxes, boxSampleRate };

  const duration = job.duration;

  // ---- drawing

  const draw = useCallback((t: number) => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth;
    const cssH = canvas.clientHeight;
    if (cssW === 0 || cssH === 0) return;
    if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const s = drawState.current;
    if (!s.showBoxes) return;

    // Hold a box for one sample period past its last sample so it does not strobe at the
    // sample boundary; beyond that the track really is gone and must not draw.
    const hold = 1 / Math.max(1e-6, s.boxSampleRate);
    const shown = visibleBoxes(s.tracks, t, hold);

    for (const { track, box } of shown) {
      const x = box.x * cssW;
      const y = box.y * cssH;
      const w = box.w * cssW;
      const h = box.h * cssH;

      const colour = track.alliance === 'red' ? RED : track.alliance === 'blue' ? BLUE : GREY;
      const identified = track.team != null;

      ctx.lineWidth = 2;
      ctx.strokeStyle = colour;
      // An unidentified track is dashed: the box is real, the attribution is not.
      ctx.setLineDash(identified ? [] : [5, 4]);
      ctx.strokeRect(x, y, w, h);
      ctx.setLineDash([]);

      const label = identified ? String(track.team) : `track ${track.trackId}`;
      ctx.font = '600 12px ui-monospace, SFMono-Regular, Menlo, monospace';
      const tw = ctx.measureText(label).width;
      const lh = 16;
      const ly = y - lh < 0 ? y + h : y - lh;
      ctx.fillStyle = colour;
      ctx.fillRect(x, ly, tw + 10, lh);
      ctx.fillStyle = '#0d0f14';
      ctx.fillText(label, x + 5, ly + 12);

      // Any event for this track within a beat of now, so a shot is visible as it happens.
      const near = s.events.filter(
        (e) => e.trackId === track.trackId && Math.abs(e.tSeconds - t) < 0.6
      );
      if (near.length > 0) {
        const low = near.some((e) => e.confidence < s.confidenceThreshold);
        ctx.strokeStyle = low ? LOW_CONF : '#ffffff';
        ctx.lineWidth = low ? 2 : 3;
        ctx.setLineDash(low ? [4, 3] : []);
        ctx.strokeRect(x - 4, y - 4, w + 8, h + 8);
        ctx.setLineDash([]);
        ctx.font = '600 11px ui-monospace, SFMono-Regular, Menlo, monospace';
        ctx.fillStyle = low ? LOW_CONF : '#ffffff';
        ctx.fillText(EVENT_LABEL[near[0].eventType], x, y + h + 13);
      }
    }
  }, []);

  // ---- frame loop
  //
  // rVFC fires once per presented video frame with the exact mediaTime of that frame, which
  // is the whole reason for a self-hosted <video> over the YouTube iframe. Fall back to rAF
  // plus currentTime where it is unavailable (Firefox), which is visibly looser.

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let handle = 0;
    let raf = 0;
    let cancelled = false;

    const rvfc = (video as Partial<RVFCCapable>).requestVideoFrameCallback;
    const cancelRvfc = (video as Partial<RVFCCapable>).cancelVideoFrameCallback;
    if (typeof rvfc === 'function') {
      const onFrame = (_now: number, meta: FrameMeta) => {
        if (cancelled) return;
        setTime(meta.mediaTime);
        draw(meta.mediaTime);
        handle = rvfc.call(video, onFrame);
      };
      handle = rvfc.call(video, onFrame);
      return () => {
        cancelled = true;
        cancelRvfc?.call(video, handle);
      };
    }

    const tick = () => {
      if (cancelled) return;
      setTime(video.currentTime);
      draw(video.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [draw, ready]);

  // Paused frames still need redrawing when the caller changes filters or the box toggle.
  useEffect(() => {
    if (!playing) draw(videoRef.current?.currentTime ?? 0);
  }, [draw, playing, tracks, events, confidenceThreshold, showBoxes]);

  // draw() bails when the canvas has no layout yet, and on first load the track data can
  // arrive before that happens -- leaving the overlay blank until the user hits play or
  // touches a filter. Redrawing on resize covers both that first sizing and any later one.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => draw(videoRef.current?.currentTime ?? 0));
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [draw]);

  useEffect(() => {
    onTimeChange?.(time);
  }, [time, onTimeChange]);

  // ---- transport

  const seek = useCallback((t: number) => {
    const video = videoRef.current;
    if (!video) return;
    const clamped = Math.max(0, Math.min(duration, t));
    video.currentTime = clamped;
    setTime(clamped);
    draw(clamped);
  }, [duration, draw]);

  useEffect(() => {
    if (seekTo) seek(seekTo.t);
    // nonce lets the parent request the same timestamp twice in a row
  }, [seekTo?.nonce, seekTo?.t, seek]);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  }, []);

  const step = useCallback(
    (frames: number) => {
      const video = videoRef.current;
      if (!video) return;
      video.pause();
      seek(video.currentTime + frames / job.fps);
    },
    [job.fps, seek]
  );

  // Keyboard transport, the way anyone reviewing footage expects it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (e.key === ' ') {
        e.preventDefault();
        togglePlay();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        step(e.shiftKey ? -30 : -1);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        step(e.shiftKey ? 30 : 1);
      } else if (e.key === 'b') {
        setShowBoxes((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [togglePlay, step]);

  // ---- scrub bar markers

  const markers = useMemo(
    () =>
      events
        .filter((e) => e.eventType === 'shot_made' || e.eventType === 'shot_attempt' || e.eventType === 'foul')
        .map((e) => ({
          id: e.eventId,
          left: (e.tSeconds / duration) * 100,
          low: e.confidence < confidenceThreshold,
          type: e.eventType,
        })),
    [events, duration, confidenceThreshold]
  );

  const selected = events.find((e) => e.eventId === selectedEventId) ?? null;

  return (
    <section className="player">
      <div className="player-stage" style={{ aspectRatio: `${job.width} / ${job.height}` }}>
        <video
          ref={videoRef}
          className="player-video"
          src={src}
          preload="auto"
          playsInline
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onRateChange={(e) => setRate((e.target as HTMLVideoElement).playbackRate)}
          onLoadedData={() => setReady(true)}
        />
        <canvas ref={canvasRef} className="player-overlay" />
        {!ready && <div className="player-loading">loading segment…</div>}
      </div>

      <div className="scrub">
        <div className="scrub-track">
          {/* Phase bands, so auto/teleop/endgame are readable at a glance. */}
          <div
            className="scrub-phase auto"
            style={{ left: 0, width: `${(PHASE_BOUNDS.autoEnd / duration) * 100}%` }}
            title="Auto"
          />
          <div
            className="scrub-phase teleop"
            style={{
              left: `${(PHASE_BOUNDS.autoEnd / duration) * 100}%`,
              width: `${((PHASE_BOUNDS.teleopEnd - PHASE_BOUNDS.autoEnd) / duration) * 100}%`,
            }}
            title="Teleop"
          />
          <div
            className="scrub-phase endgame"
            style={{
              left: `${(PHASE_BOUNDS.teleopEnd / duration) * 100}%`,
              width: `${((PHASE_BOUNDS.matchEnd - PHASE_BOUNDS.teleopEnd) / duration) * 100}%`,
            }}
            title="Endgame"
          />
          {markers.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`scrub-marker ${m.type} ${m.low ? 'low' : ''} ${m.id === selectedEventId ? 'on' : ''}`}
              style={{ left: `${m.left}%` }}
              title={`${EVENT_LABEL[m.type as keyof typeof EVENT_LABEL]} @ ${fmtTime((m.left / 100) * duration)}`}
              onClick={() => onSelectEvent(m.id)}
            />
          ))}
          <div className="scrub-playhead" style={{ left: `${(time / duration) * 100}%` }} />
          <input
            className="scrub-input"
            type="range"
            min={0}
            max={duration}
            step={1 / job.fps}
            value={time}
            onChange={(e) => seek(Number(e.target.value))}
            aria-label="Seek"
          />
        </div>
      </div>

      <div className="transport">
        <button type="button" onClick={() => step(-30)} title="Back 1s (Shift+Left)">«</button>
        <button type="button" onClick={() => step(-1)} title="Previous frame (Left)">‹</button>
        <button type="button" className="primary" onClick={togglePlay} title="Play/pause (Space)">
          {playing ? 'Pause' : 'Play'}
        </button>
        <button type="button" onClick={() => step(1)} title="Next frame (Right)">›</button>
        <button type="button" onClick={() => step(30)} title="Forward 1s (Shift+Right)">»</button>

        <span className="transport-time" title="Segment time, and position in the original video">
          <strong>{fmtTime(time)}</strong>
          <span className="muted"> / {fmtClock(duration)} seg</span>
        </span>

        <label className="transport-rate">
          Speed
          <select
            value={rate}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (videoRef.current) videoRef.current.playbackRate = v;
              setRate(v);
            }}
          >
            {[0.25, 0.5, 1, 1.5, 2].map((r) => (
              <option key={r} value={r}>{r}×</option>
            ))}
          </select>
        </label>

        <label className="transport-toggle" title="Toggle overlay (B)">
          <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} />
          Boxes
        </label>

        {/* The one place component 3 adds start_offset -- doc 0 says nothing else ever should. */}
        <a
          className="yt-link"
          href={youtubeUrlAt(job.videoId, time, job.startOffset)}
          target="_blank"
          rel="noreferrer"
          title={`Original video at ${fmtClock(time + job.startOffset)} (segment ${fmtClock(time)} + ${job.startOffset}s offset)`}
        >
          Open on YouTube ↗
        </a>
      </div>

      {selected && (
        <div className={`player-selected ${selected.confidence < confidenceThreshold ? 'low' : ''}`}>
          <strong>{EVENT_LABEL[selected.eventType]}</strong>
          <span>{selected.team != null ? `team ${selected.team}` : 'unattributed'}</span>
          <span className="muted">{fmtTime(selected.tSeconds)}</span>
          <span className="muted">conf {selected.confidence.toFixed(2)}</span>
          <button type="button" onClick={() => onSelectEvent(null)}>clear</button>
        </div>
      )}
    </section>
  );
}
