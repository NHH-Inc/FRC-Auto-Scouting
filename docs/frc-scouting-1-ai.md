# Project Tengen — 1. AI and Computer Vision

One of three context documents. This one covers the analysis backend: models, tracking, event extraction, and training data. Video acquisition is in document 2. The web app, storage, and export are in document 3.

## Project background

A tool that watches recorded FRC match video and produces per-robot scouting data. Input is a match video. Output is a stream of timestamped events attributed to individual teams.

The point is per-robot attribution. Match-level results (final score, auto/teleop split, fouls, ranking points) are already published by The Blue Alliance and Statbotics, and pulling them from an API is free and exact. Video analysis is only worth doing for what the API does not contain: which of the three robots on an alliance did what, how long its cycles took, how accurate it was, where it spent its time.

TBA is also the accuracy check. If the pipeline's reconstructed score does not match TBA's official score for the same match, the pipeline is wrong. That comparison is the main evaluation loop and should exist before any of the fancier features.

## Stack

C++. OpenCV for decode and image ops, ONNX Runtime or TensorRT for inference, a C++ ByteTrack implementation for tracking. The backend consumes a video file and emits an event stream. It does not talk to the browser directly.

## Model

Custom-trained detector. Classes: robots, game pieces, goals, field landmarks.

Robot detection stays generic across seasons, since robots look like robots every year. Game-piece and goal classes are season-specific and swappable via config, because the game changes every January.

Licensing matters if this ends up closed-source. RF-DETR is Apache 2.0 and currently the strongest general-purpose detector. Ultralytics YOLO is AGPL-3.0 and generally requires a paid enterprise license for closed-source commercial use.

## Tracking

The detector produces boxes per frame. ByteTrack links them into tracks across frames.

A homography maps image coordinates onto a top-down field plane, using fixed field landmarks as anchors. Field dimensions are known and constant, so this gives positions in real feet. Without it, coordinates are pixels and mean nothing across different camera angles. Speed, zone occupancy, and defense metrics all depend on this.

Shot-change detection is required. Official streams cut to replays and closeups, which invalidates the homography and breaks tracks. Those segments should be detected and skipped, not analyzed.

Skipped intervals must be reported explicitly in each track's `gaps` array (Contract C) with `reason: "shot_change"`. Same for occlusion, out-of-frame and lost detection. Without this, a four-second hole is indistinguishable from a low sample rate and the frontend draws a robot gliding through footage nobody analyzed. Do not split a track at a gap: re-identification exists to stitch fragments into one logical track, and splitting undoes it.

`phase` is not detected. It is a pure function of match-relative time and the season config at `/contracts/seasons/<year>.json`, specified in document 0. Read `auto_seconds`, `teleop_seconds` and `endgame_seconds` from that file. Hardcoding 15, 135 or 20 will silently disagree with the frontend's timeline bands.

## Robot identification

ByteTrack assigns arbitrary track IDs. Mapping a track ID to a team number is the hardest part of the project.

Primary method is OCR on bumper numbers. Reads will be intermittent because bumpers are small, in motion, and often facing away from the camera. Approach: whenever a confident read happens, stamp that team number onto the track and propagate it across the track's full lifetime, backward and forward.

Bumper color gives alliance (red or blue) reliably, which cuts the candidate set to three. TBA supplies the three teams per alliance for a given match, so the search space is tiny. A single confident read on one robot plus process of elimination often resolves the other two.

Tracks will break during occlusion in the scoring zone. A re-identification step should stitch fragments back together using appearance embeddings plus accumulated bumper reads.

## Event extraction

Game pieces are not tracked in flight. They are too small, too fast, and they leave frame. Events are inferred from robot state and region overlap instead:

- Shot attempt: robot in shooting pose, or pieces leaving the robot
- Made shot: scoring event detected at the goal region
- Reload: robot overlapping a source or human player station
- Shot rate: interval between consecutive shot events, not projectile velocity
- Cycle time: interval between consecutive `reload` events for the same **team**. Acquire to acquire, so a missed shot still costs a cycle. Per team rather than per track, because track ids are job-local and a re-identified robot may span several. Definition lives in document 0's vocabulary section; do not redefine it here.

Everything is correlated by timestamp, then validated against the TBA score total for the match.

## Scoreboard OCR

Separate from bumper OCR. Many broadcast streams overlay a live score, timer, and phase indicator. When present it is the cheapest possible source of truth for the auto/teleop boundary and for score deltas, which can be diffed frame to frame to detect scoring moments the vision pipeline missed.

Overlay position and design change every season and vary between event AV setups, so treat the scoreboard region as a per-source config, not a hardcoded crop.

## Output format

**Do not build the event row from this document. Contract B in document 0 is authoritative.** An earlier version of this section listed an eight-field subset that is missing `schema_version`, `job_id`, `event_id`, `track_id` and `source`. Emitting that subset breaks the corrections layer, the accuracy comparison and the training-data export.

Three outputs per run, all specified in document 0:

- `events.jsonl` — Contract B, one JSON object per line, ascending by `t_seconds`
- `tracks.jsonl` — Contract C, one object per track, `gaps` array required
- `result.json` — Contract D, pinned key names

`event_id` is generated here, not by the database, because corrections reference it before anything is stored. Every event carries a confidence value and a `source`. Nothing is aggregated at this layer; aggregation happens downstream as queries over the event table.

## Training data

Labeling is the bulk of the work, not the code. Realistically thousands of annotated frames spanning multiple venues, lighting conditions, and camera positions. A model trained on one event's footage will not transfer to the next venue.

Workflow: auto-label a first pass with Grounding DINO or YOLO-World using text prompts, correct by hand in CVAT or Roboflow, then train. User corrections from the app's correction UI feed back in as additional labeled data.

Everything game-specific expires at the end of the season. The re-annotation pipeline needs to be a one-week job, not a six-month one.

## Scope

The full feature list is multiple seasons of work. The first version should target one metric, one event, one camera angle, and be accurate at it. Per-robot cycle time alone is useful enough to hand to a drive team.

## Working preferences

Direct answers, no hedging. Plain explanations over dense technical prose. Do not restate this document back; assume it is understood and answer the actual question.
