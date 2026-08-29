# yt-dlp media streaming and model data contract

This document defines how a queued YouTube link becomes an ad-free local preview, a durable media
artifact, and time-aligned robot overlays. Treat the timing and coordinate rules below as an API
contract when adding a detector, tracker, annotator, or training exporter.

## Data flow

```text
pasted YouTube link
  -> POST /api/jobs
  -> yt-dlp metadata: video_id, start_offset, duration
  -> GET /api/stream/<job-id>/video + /audio
       -> short-lived signed DASH media URLs resolved by local yt-dlp
       -> byte-range proxy on localhost
       -> native <video> + synchronized hidden <audio>
       -> canvas boxes from tracks.jsonl

background job
  -> yt-dlp + ffmpeg merge/cut
  -> data/segments/<video-window>.mp4
  -> analyzer and data/collection frame extraction
  -> data/jobs/<job-id>/events.jsonl + tracks.jsonl
```

The stream is a review convenience. The background download is the durable source for analysis,
dataset extraction, training, evaluation, and reproducible inference.

## Media endpoints

| Endpoint/source | Media clock | Intended use |
|---|---|---|
| `/api/stream/<job-id>/video` | Original YouTube recording time | Immediate native preview; prefers H.264 MP4 at 720p or lower |
| `/api/stream/<job-id>/audio` | Original YouTube recording time | Separate M4A/DASH audio synchronized by the player |
| `/api/video/<job-id>` | Segment time starting at zero | Completed, merged local segment for stable review |
| `data/segments/*.mp4` | Segment time starting at zero | Analyzer, collection extraction, training, and evaluation |

Both stream routes support browser `Range` requests and relay content-range and cache validators.
They accept only a stored job ID and a fixed `video` or `audio` kind, so the API is not an arbitrary
URL proxy. Signed upstream URLs remain behind the ingest service and are cached for 15 minutes only
to reduce yt-dlp resolution work. Their lifetime is not part of data provenance.

YouTube normally supplies separate video and audio DASH files. If yt-dlp selects a legacy combined
file, both local endpoints proxy that file and the visible video element is muted; the hidden audio
element remains the single audio clock.

## Time-coordinate invariant

Every event and track timestamp in repository contracts is **segment-relative seconds**.

```text
segment_time = source_media_time - job.start_offset
```

- The live yt-dlp stream represents the full original recording. The player seeks it to
  `job.start_offset` and subtracts that offset when selecting overlays or reporting match time.
- The downloaded MP4 has already been cut. Its first frame is segment time `0`, so the player and
  models use its media time directly.
- A model consuming the full-source stream must subtract `start_offset` exactly once before writing
  output. A model consuming `data/segments/*.mp4` must not add or subtract it.
- Keep `start_offset`, source URL, video ID, and media checksum in collection provenance. Never infer
  timing from a filename alone.

Mixing these clocks shifts every box and event by the URL timestamp while still producing
syntactically valid data, so consumers should test the boundary at segment times 0 and 1 second.

## Box-coordinate invariant

Robot boxes use normalized, top-left coordinates over the decoded source frame:

```text
x, y, w, h in [0, 1]
pixel_x = x * decoded_video_width
pixel_y = y * decoded_video_height
```

The box covers the full physical robot extent when it can be inferred, including partial occlusion.
The canvas is sized from the native video's decoded width and height, then CSS-scales the video and
canvas together. Models must not emit coordinates relative to letterboxing, the browser viewport,
or the visible canvas size.

## Rules for model integrations

1. Extract training/evaluation frames only from the immutable MP4 in `data/segments/`, using
   `python -m ingest.collection.cli extract`. Do not scrape frames from the stream endpoints.
2. Emit segment-relative timestamps and normalized top-left boxes regardless of the model's input
   resolution. Preserve the decoded frame timestamp rather than reconstructing it from frame count.
3. Keep automatic output as `status: proposed` and `human_review_required: true`. Agreement among
   multiple Ollama models prioritizes review; it does not create ground truth.
4. Preserve each model's raw proposals separately. Accepted annotations and immutable dataset
   exports are distinct artifacts and must retain source checksums and configuration snapshots.
5. Use the completed local segment for exact replay, audio-event inference, regression tests, and
   comparisons across models. Network stream timing and availability are not reproducible inputs.

See `data-collection.md` for the Ollama commands and generated artifact layout, and
`frc-scouting-0-contract.md` for the authoritative event and track schemas.

## Player synchronization

The visible `<video>` element drives rendering through `requestVideoFrameCallback`. Transport
controls seek, pause, and set playback rate on both native elements. The audio clock is corrected
when it drifts by more than 120 ms. Overlay lookup always uses the segment time derived above.

If synchronized preview fails, wait for the background download and choose **Downloaded file**.
That path is also the correct choice for close frame-by-frame annotation.

## Local operation and diagnosis

Start the ingest and web services as described in the repository README. Then verify that a queued
job supports byte ranges:

```bash
curl -i -H 'Range: bytes=0-1023' \
  http://127.0.0.1:8080/api/stream/<job-id>/video
curl -i -H 'Range: bytes=0-1023' \
  http://127.0.0.1:8080/api/stream/<job-id>/audio
```

A healthy response is `206 Partial Content`. Authentication-limited videos can use
`YTDLP_COOKIES_FROM_BROWSER=chrome`. Keep yt-dlp current because upstream YouTube formats and
signatures change independently of this repository.

Relevant implementation files are `ingest/downloader.py`, `ingest/main.py`,
`web/src/player/VideoPlayer.tsx`, and `web/src/App.tsx`.
