import { useCallback, useEffect, useMemo, useState } from 'react';
import { getApi } from './api';
import { isPlayable } from './contracts';
import { EventInspector } from './components/EventInspector';
import { ExportPanel } from './components/ExportPanel';
import { Sidebar } from './components/Sidebar';
import { VideoPlayer } from './player/VideoPlayer';
import { useJobs } from './state/useJobs';
import { useMatch } from './state/useMatch';
import { AccuracyPanel } from './views/Accuracy';
import { HeatMap } from './views/HeatMap';
import { TeamStats } from './views/TeamStats';
import { Timeline } from './views/Timeline';

type Tab = 'timeline' | 'teams' | 'heatmap' | 'accuracy' | 'export';

const TABS: Array<[Tab, string]> = [
  ['timeline', 'Timeline'],
  ['teams', 'Team stats'],
  ['heatmap', 'Heat map'],
  ['accuracy', 'Accuracy'],
  ['export', 'Export'],
];

export default function App() {
  const jobsState = useJobs();
  const { jobs } = jobsState;

  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [selectedTeam, setSelectedTeam] = useState<number | null>(null);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.5);
  const [tab, setTab] = useState<Tab>('timeline');
  const [currentTime, setCurrentTime] = useState(0);
  const [seekTo, setSeekTo] = useState<{ t: number; nonce: number } | null>(null);
  const [apiMode, setApiMode] = useState<'http' | 'fixture'>('fixture');
  const [videoSrc, setVideoSrc] = useState<string | null>(null);

  useEffect(() => {
    void getApi().then((api) => setApiMode(api.mode));
  }, []);

  // Land on something watchable rather than an empty stage.
  useEffect(() => {
    if (selectedJobId || jobs.length === 0) return;
    setSelectedJobId((jobs.find((j) => j.status === 'complete') ?? jobs[0]).jobId);
  }, [jobs, selectedJobId]);

  const job = useMemo(
    () => jobs.find((j) => j.jobId === selectedJobId) ?? null,
    [jobs, selectedJobId]
  );

  useEffect(() => {
    if (!job) {
      setVideoSrc(null);
      return;
    }
    void getApi().then((api) => setVideoSrc(api.videoUrl(job)));
  }, [job]);

  const match = useMatch(job?.matchId ?? null);

  // A complete job whose media metadata never arrived cannot drive a player -- rather than
  // defaulting a duration and drawing a wrong scrub bar, the stage says so.
  const playable = isPlayable(job) ? job : null;

  const seek = useCallback((t: number) => {
    setSeekTo({ t, nonce: Date.now() });
  }, []);

  const matchIds = useMemo(
    () => [...new Set(jobs.map((j) => j.matchId).filter((m): m is string => m != null))],
    [jobs]
  );

  return (
    <div className="app">
      <Sidebar
        jobs={jobs}
        loading={jobsState.loading}
        error={jobsState.error}
        violations={[...jobsState.violations, ...match.violations]}
        selectedJobId={job?.jobId ?? null}
        apiMode={apiMode}
        onSelectJob={(id) => {
          setSelectedJobId(id);
          setSelectedEventId(null);
        }}
        onCreate={jobsState.createJob}
        onDelete={jobsState.deleteJob}
        onRetry={jobsState.retryJob}
      />

      <main className="main">
        {!job && <div className="stage-empty">Queue a video, or pick one from the queue.</div>}

        {job && job.status !== 'complete' && (
          <div className="stage-empty">
            <p>
              <strong>{job.matchId ?? job.videoId}</strong> is {job.status}.
            </p>
            <p className="muted">
              {job.status === 'failed'
                ? 'Retry from the sidebar — the video ID is stored on the job, so there is nothing to re-paste.'
                : 'The player opens once analysis finishes.'}
            </p>
          </div>
        )}

        {job && job.status === 'complete' && !playable && (
          <div className="stage-empty">
            <p>
              <strong>{job.matchId ?? job.videoId}</strong> is complete, but the job record has
              no media metadata.
            </p>
            <p className="muted">
              duration, fps, width and height are still null. The ingest service has to write
              them back to the job row once the download reports them — see
              contracts/job.schema.json, which requires them from status <code>downloaded</code>
              onward.
            </p>
          </div>
        )}

        {job && job.status === 'complete' && playable && videoSrc && (
          <>
            <VideoPlayer
              job={playable}
              src={videoSrc}
              tracks={match.tracks}
              events={match.events}
              confidenceThreshold={confidenceThreshold}
              boxSampleRate={match.boxSampleRate}
              selectedEventId={selectedEventId}
              onSelectEvent={setSelectedEventId}
              seekTo={seekTo}
              onTimeChange={setCurrentTime}
            />

            <nav className="tabs">
              {TABS.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={tab === id ? 'on' : ''}
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
              <span className="tabs-meta muted">
                {match.loading
                  ? 'loading…'
                  : `${match.events.length} events · ${match.tracks.length} tracks · boxes @ ${match.boxSampleRate.toFixed(0)} Hz`}
              </span>
            </nav>

            {match.error && <p className="error">{match.error}</p>}

            {tab === 'timeline' && (
              <Timeline
                job={playable}
                events={match.events}
                confidenceThreshold={confidenceThreshold}
                currentTime={currentTime}
                selectedEventId={selectedEventId}
                onSelectEvent={setSelectedEventId}
                onSeek={seek}
              />
            )}
            {tab === 'teams' && (
              <TeamStats
                job={job}
                events={match.events}
                selectedTeam={selectedTeam}
                onSelectTeam={setSelectedTeam}
              />
            )}
            {tab === 'heatmap' && <HeatMap events={match.events} selectedTeam={selectedTeam} />}
            {tab === 'accuracy' && <AccuracyPanel accuracy={match.accuracy} fromRaw />}
            {tab === 'export' && <ExportPanel matchIds={matchIds} />}
          </>
        )}
      </main>

      {job && job.status === 'complete' && (
        <EventInspector
          job={job}
          events={match.events}
          deleted={match.deleted}
          currentTime={currentTime}
          confidenceThreshold={confidenceThreshold}
          onConfidenceThreshold={setConfidenceThreshold}
          selectedEventId={selectedEventId}
          onSelectEvent={setSelectedEventId}
          onSeek={seek}
          onPatch={match.patchEvent}
          onDelete={match.removeEvent}
          onCreate={match.addEvent}
        />
      )}
    </div>
  );
}
