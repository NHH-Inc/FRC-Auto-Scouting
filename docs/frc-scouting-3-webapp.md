# FRC Video Scouting — 3. Web App, UI, and Data

One of three context documents. This one covers the frontend, storage, and export. The vision and event pipeline is in document 1. Video acquisition is in document 2.

## Project background

A tool that watches recorded FRC match video and produces per-robot scouting data. The C++ analysis backend consumes a video and emits a stream of timestamped events attributed to individual teams. This document covers everything that happens to those events afterward: displaying them, correcting them, storing them, and exporting them.

The frontend is web (HTML/JS), not C++. The backend never talks to the browser directly. It emits an event stream, and that stream is what the frontend renders.

## Layout

Video player as the main surface. Sidebar for pasting YouTube links, viewing queue status, and browsing extracted results. Bounding boxes drawn over the video, labeled with team numbers.

## Player and overlay

Boxes are drawn on an absolutely positioned canvas layered over the player, redrawn per animation frame from the event/track data.

There are two ways to do the player, and the choice determines whether the overlay is usable:

- **YouTube iframe embed.** Sync comes from `getCurrentTime()`, which is coarse and drifts. The overlay will visibly lag and jitter against the video. Acceptable for a rough preview, not for frame-accurate review.
- **Self-hosted `<video>` element** playing the downloaded file. Gives real frame accuracy via `requestVideoFrameCallback`, which is what you actually want for reviewing and correcting box placement.

Since the pipeline already downloads the file with yt-dlp (document 2), serving that file locally is the obvious choice for the analysis view. The iframe is only needed if the goal is to display video the tool has not downloaded.

If segments were clipped out of a longer stream, the player needs the `start_offset` to translate between segment time and original video time.

## Correction UI

Build this early. Users will find wrong calls, and a tool that cannot be corrected will not be trusted.

Minimum useful version: scrub to an event, see what the pipeline claimed, fix the team attribution or delete the event, add a missed one. Corrections serve two purposes at once. They fix the user's data, and they become labeled training data for the next model iteration.

Every event carries a confidence score. Surface it, and let users filter the view by threshold. Low-confidence events should be visually distinct so people know where to look first.

## Views

- Per-match timeline of events for all six robots
- Per-team aggregate stats across an event or a season
- Field heat maps, once homography is working, showing where a robot spends time
- Reconstructed score vs. TBA official score, as a visible accuracy indicator per match

## Storage

Raw timestamped events are the source of truth. One row per event:

```
{ match_id, team, t_seconds, phase, event_type, confidence, field_x, field_y }
```

Never store aggregates as primary data. Every stat is a query over the event table. Postgres or SQLite.

Corrections should be stored as their own layer rather than overwriting the original events, so the model's raw output stays available for evaluation. A view that applies corrections on top of raw output gives you both.

## Google Sheets export

Sheets is an export destination, not storage. The Sheets API will not hold up if treated as a database.

Export writes a flat denormalized table shaped for how scouts actually use spreadsheets: one row per team per match, columns for the aggregate stats. Batch the writes; per-row API calls will hit quota immediately.

Give users the choice of exporting raw events or aggregates, and make re-export idempotent so running it twice does not duplicate rows.

## Job handling

Download and analysis are long-running. The UI needs a queue with visible status per video: queued, downloading, analyzing, done, failed. Failures are routine (see document 2) and need a retry path that does not require re-pasting the link.

## Scope

The full feature list is multiple seasons of work. The first version should target one metric, one event, one camera angle, and be accurate at it. Per-robot cycle time alone is useful enough to hand to a drive team.

## Working preferences

Direct answers, no hedging. Plain explanations over dense technical prose. Do not restate this document back; assume it is understood and answer the actual question.
