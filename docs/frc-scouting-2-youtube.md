# FRC Video Scouting — 2. YouTube and Video Acquisition

One of three context documents. This one covers getting match video off YouTube and matching it to real matches. The vision and event pipeline is in document 1. The web app, storage, and export are in document 3.

## Project background

A tool that watches recorded FRC match video and produces per-robot scouting data. Users paste a YouTube link, or a match is resolved to a video automatically. The video is downloaded, handed to a C++ analysis backend, and turned into a stream of timestamped events attributed to individual teams.

## Downloader

yt-dlp (https://github.com/yt-dlp/yt-dlp). Requires ffmpeg on the host for merging and remuxing.

Practical notes:

- yt-dlp breaks regularly when YouTube changes things. Do not pin an old version. Update it on a schedule and treat a failed download as an expected condition, not a crash.
- Some videos require cookies or a PO token to fetch. `--cookies-from-browser` handles the common cases.
- Format selection: cap the resolution rather than taking whatever is best. 720p or 1080p is plenty for detection, and pulling 4K wastes bandwidth and decode time. Something like `bv*[height<=1080]+ba/b[height<=1080]`.
- `--dump-json` gets metadata (title, duration, upload date, channel) without downloading the media. Use it to validate a link before queueing a real download.
- Rate limits are real. Serial downloads with backoff, not a parallel fleet. If the tool gets popular, this is the first thing that breaks.

Downloading video at scale is against YouTube's terms of service. This is a known and accepted tradeoff for the project, but it shapes the architecture: assume downloads can fail or be throttled at any time, cache aggressively, and never re-download something already processed.

## Long streams vs. individual match uploads

This is the biggest practical problem and it is easy to miss.

Most official FRC event footage is not one video per match. It is a multi-hour livestream VOD covering an entire day of play. A single 2:30 match sits somewhere inside a six-hour file.

TBA match objects include a `videos` array with YouTube keys when available. Some of those are individual match uploads from event AV teams or archive channels. Some are timestamped links into a long stream. Handle both.

For long VODs, `--download-sections "*HH:MM:SS-HH:MM:SS"` pulls only the relevant window without fetching hours of footage. This turns a six-hour download into a three-minute one and is essential for anything resembling scale.

## Match-to-video alignment

Given a video and a timestamp, you still need to know which match it is, and given a match you need to find its window in a stream.

Sources of alignment, in rough order of reliability:

1. TBA `videos` field with an explicit match association
2. Timestamp in a YouTube link (`&t=`) or in the video description, which official channels often include as a chapter list
3. Scoreboard OCR on the video itself, reading the match number off the broadcast overlay
4. Detecting the match start signal (field lights, timer starting at 15 for auto) to find precise match boundaries within a window

The auto period is exactly 15 seconds and teleop is exactly 135 seconds in current games, so once the start frame is located, the phase boundaries are deterministic and do not need to be inferred.

## Metadata

Use the YouTube Data API for metadata (title, channel, duration, publish date), not scraping. It has a free quota and is stable. Use TBA for everything about the match itself.

## Caching and storage

Key everything by YouTube video ID plus, for long streams, the time window. Never process the same segment twice.

Downloaded media is a cache, not a record. It should be deletable at any time without losing anything: the event data extracted from it is the actual product and lives in the database. Set a retention policy early or disk usage will get out of hand fast, since a single event's footage is tens of gigabytes.

Store the extracted segment rather than the full VOD when possible.

## Handoff to the analysis backend

The downloader's job ends when it produces a local file plus a metadata record:

```
{ video_id, match_id, local_path, start_offset, duration, source_channel, resolution, fps }
```

`start_offset` matters: if the segment was clipped out of a longer stream, every timestamp the analysis backend emits needs to be translatable back to a position in the original video so the frontend can seek to it.

Decode happens in the C++ backend via OpenCV, not here. This stage only acquires files.

## Working preferences

Direct answers, no hedging. Plain explanations over dense technical prose. Do not restate this document back; assume it is understood and answer the actual question.
