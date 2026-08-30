# Decision log

Project decisions that are not contract changes. Each one is reversible; they are written
down so that changing one is a conversation about that one thing rather than an archaeology
dig through Discord.

Contract changes do **not** belong here — those go through `contracts/OPEN_QUESTIONS.md` and
need all three people, per doc 0.

| Status | Meaning |
|---|---|
| **settled** | A person decided it. |
| **default** | Nobody had a preference, so the recommended option was taken. Overrule freely. |
| **blocked** | Decided, but waiting on an action only a human can take. |

---

## Contract

**D0 — `goal` on Contract B, SCHEMA_VERSION 3.** `settled` (all three)
An optional, nullable field saying which goal a shot went into. Deliberately **not** a closed
set in doc 0: legal values are the season config's `goals`, because they change every
January — 2026 is `high | low`, 2025 is `l1 | l2 | l3 | l4 | processor | net`. A doc-0 enum
would need editing every season, which is the churn closed sets exist to avoid. Validation
reads the season config; a schema cannot know which season it is looking at.

Null means the model could not place the shot, and it scores zero rather than guessing — that
keeps the accuracy comparison honest about what the pipeline actually knows.

## Labelling pipeline

**D1 — Nathaniel's model is a classifier.** `settled` (Nathaniel)
Team ID from a robot crop. He was not attached to either answer and asked us to pick, so:
classifier. That makes the crop step in the ensemble plan correct as written, and it means the
detector and the team-ID model are trained from different data — boxes for one, crops for the
other.

**D2 — Consensus is intersection-over-union, not coordinate averaging.** `settled` (Robert)
Per-model raw results are retained for auditing. Averaging fails silently — one model missing
the robot drags the box onto empty carpet with nothing in the output to show it. IoU consensus
can at least report that the models disagreed.

**D3 — Model stack: `qwen3-vl:4b`, `qwen2.5vl:7b`, `gemma3:4b`.** `settled` (Robert)
Run sequentially so they fit in memory, ~12–13 GB on disk. No Ultralytics, so doc 1's AGPL
concern does not arise. Two of the three share a family, so `gemma3` carries all of the actual
diversity — see the open measurement below.

**D4 — The correction UI is the label source for team identification.** `default`
Every track re-attribution is already a human-confirmed (track → team) pair, reviewed by
construction, and it grows as people scout. The ensemble still earns its place for robot
*detection*, where there are no human-labelled boxes at all.

**D5 — v1 trains on unreviewed auto-labels for detection.** `default`
Accepted with eyes open: the first detector is capped at roughly the ensemble's quality,
because that is what generated its labels. Doc 1's hand-correction step is skipped for v1 and
picked up when Roboflow is in place (D8).

**Open measurement — is `gemma3:4b` contributing a real vote?**
The two Qwen-VL models are trained for grounding; Gemma 3 takes image input but is not trained
for bounding-box grounding the same way. If it rarely agrees, a 2-of-3 quorum quietly becomes
"the two Qwens agreed", which is close to one family voting twice. The per-model raw results
already being kept make this ~20 minutes of work: take 50 frames, measure each model's IoU
against the fused box, compare agreement rates.

Related: start the IoU threshold around **0.4**, not the usual 0.5. A robot in a wide field
shot is often under 5% of frame width, and IoU is harsh on small objects — at that scale a few
pixels of honest disagreement drops a genuine match below 0.5.

## Training data storage

**D6 — Store references, not frames.** `default`
`(video_id, start_offset, frame_number)` plus boxes; regenerate frames with ffmpeg at training
time. For 100k labelled frames that is ~15 MB instead of 20–50 GB, small enough to live in git
and be reviewed in pull requests. Same principle doc 2 already commits to: media is a cache,
not a record.

**D7 — Materialised crops go in sharded archives.** `default`
~10k images per shard, WebDataset layout. Many-small-files is what kills every backend, not the
byte count: 100k crops at ~6 KB is only ~600 MB, trivial as ten shards and painful as 100,000
files.

**D8 — Roboflow free tier for the dataset and review UI.** `default`
It doubles as the hand-correction step D5 defers, and exports YOLO/COCO. Not Google Drive:
per-file API overhead, rate limits, no random access, no content addressing. Cloudflare R2 is
the fallback if we outgrow it (S3-compatible, zero egress fees). Not Git LFS — 1 GB quota.

**D9 — Segments are deleted once analysed, with a 7-day grace window.** `default`
Safe because the events are the product and they live in the database. Doc 2: "set a retention
policy early or disk usage will get out of hand fast" — a single event's footage is tens of GB.
Deleting a job already removes its segment, so this is a scheduled sweep, not new machinery.

## Operations

**D10 — TBA key lives in `ingest/.env`, never committed.** `settled` (Justin)
Key created and in place; `git check-ignore` confirms `ingest/.env` cannot be committed.

Verified against the live API, which caught a real bug: `find_match_for_video` was querying
`/event/<key>/matches/simple`, and the *simple* representation omits the `videos` array — so
video-to-match resolution could never have matched anything. Fixed to use the full endpoint.
Now confirmed end to end: 324 events for 2024, alliances returned with the `frc` prefix
stripped to integers, real scores, and `m_uFap-LvzU` resolving to `2024week0_f1m1`.

**D11 — Export spreadsheet.** `blocked` on one file
Sheet is `1oF8oumoi1f7wWQGszfF4XcOD8rDUWo08RrkMttRg9bI`, and `SHEETS_SPREADSHEET_ID` is set in
`ingest/.env`. `google-api-python-client` and `google-auth` are installed.

Still missing: a service account JSON at `GOOGLE_APPLICATION_CREDENTIALS`, and the sheet shared
with that service account's email as an **Editor**. Link-sharing is not enough — the Sheets API
authenticates as the service account, so it needs its own grant.

Until then the endpoint returns 503. That is deliberate: doc 3 treats the spreadsheet URL as
required output, and reporting a write that never happened is worse than refusing.

**D12 — CI compiles component 1; MSVC + vcpkg for local Windows builds.** `default`
`.github/workflows/ci.yml` builds `analysis/` on every push and runs a Contract D smoke test
against the golden fixture. This exists because component 1 was brought to SCHEMA_VERSION 2 by
someone with no C++ toolchain and sat in main unverified — nobody should need a local toolchain
to find out whether the C++ compiles.

## Hardware

**H1 — Justin runs the ingest service, the labelling pass, and the web app.** `settled`
Ryzen 7 7800X3D, 32 GB DDR5-6000, Radeon RX 7800 XT (16 GB), ~107 GB free.

He does **not** train. PyTorch has no AMD support on Windows — the ROCm wheels are Linux-only —
so the 7800 XT cannot train there regardless of how capable the silicon is. Ollama *does*
support RDNA3 on Windows (gfx1101), so the three VLMs run GPU-accelerated for labelling, and
16 GB VRAM holds all three at once.

**H2 — Robert trains.** `settled`
RTX 3060 **12 GB**, ~40 GB free. CUDA, so the whole PyTorch ecosystem just works, and 12 GB
fine-tunes a detector at 640px with a normal batch size — no gradient accumulation needed.

40 GB free is the constraint, not the GPU. It is another reason the dataset lives on Roboflow
(D8) rather than as local copies on three machines.

**H3 — Nobody has a usable Linux machine.** `settled`
Justin's is an i3 with 8 GB DDR4, which rules out ROCm training on his 7800 XT. Not worth
dual-booting for while Robert's CUDA box exists.

**H4 — Disk is the binding constraint, on every machine.** `settled`
107 GB free on Justin's box, 40 GB on Robert's. Doc 2: a single event's footage is tens of GB.

This is why D6 and D9 are not optimisations:

| | Size |
|---|---|
| Full 6-hour event VOD @1080p | 15–25 GB |
| One clipped match segment (2:30 @1080p) | 300–600 MB |
| 100k labelled frames as JPEGs | 20–50 GB |
| 100k frames as references + boxes | ~15 MB |

Clipping match windows instead of whole VODs is what makes this fit at all. Also note Justin's
drive is a DRAM-less Kingston SNV3S1000G — sustained writes slow sharply once the SLC cache
fills, so it is a working disk, not an archive.

**H5 — The robotics classroom machines are a real option, but ask first.** `open`
About 20 PCs: RTX 5070 Ti (16 GB), Ryzen 7 7700X, 32 GB DDR5, ~800 GB free, Windows 11. That is
substantially faster than anything we own, the labelling pass is embarrassingly parallel, and
the storage problem disappears.

Three things to settle before counting on them:

1. **Permission and install rights.** Ollama needs an installer, and school images are often
   locked down or re-imaged nightly, which would wipe local state between sessions.
2. **Do not download video on school infrastructure.** Doc 2 is explicit that bulk downloading
   is against YouTube's terms, and accepts that tradeoff for our own machines. Running it on
   school equipment and a school network makes it the school's problem rather than ours, which
   is not ours to decide. Download at home; carry the segments in on a drive.
3. **What survives a reboot.** If the machines reset, they can only do stateless GPU work —
   which is exactly what the labelling pass is, so that is fine, but the inputs and outputs have
   to live somewhere else.

Used that way — offline, stateless, after hours, with permission — they are the best compute we
have access to by a wide margin.

## Pipeline status

**P1 — Steps 4 and 5 of the labelling pipeline do not exist.** `open`
Download, frame extraction and VLM annotation all work. **Human review and training do not** —
there is no trainer anywhere in the repo, and Roboflow is decided but not set up.

Worth stating plainly because "how do I run the training" is a reasonable question with an
unreasonable answer right now. What is settled: RF-DETR on Robert's 12 GB card, dataset and
review on Roboflow, detector and team-ID classifier trained separately from different data.

**P2 — Component 1 is the critical path.** `open`
The OpenCV pipe proof now opens a real segment, counts decoded frames, and emits one diagnostic
track through the overlay. Detection, tracking, OCR, and events are still not built, so this is a
plumbing milestone rather than usable scouting output. The detector remains the critical path.

## Ownership

**O1 — Robert takes component 1 as well.** `settled`
Nathaniel is busy, so the C++ analysis backend moves to Robert. He now owns components 1 and 2:
detection/tracking/OCR, and the ingest service he already built. Justin keeps component 3 plus
running the ingest service in practice.

Doc 0's table still lists component 1 against Nathaniel; this entry supersedes it. Everything
else about the boundary is unchanged — component 1 is still a command-line binary that reads
files and writes files, still must not touch the database or the network, and still talks to
nobody except through Contract D.

Practical consequence: Robert is now on both sides of the Contract D boundary. That makes it
easy to "just make them match" instead of following the contract. Don't. Component 3 is written
against doc 0, and CI checks the binary's output against it independently.

**O2 — Robert also takes review, training, Sheets and the classroom ask.** `settled`
Roboflow setup, the detector trainer, the Google service account, and asking about the
classroom machines are all his.

**This concentrates almost the whole project on one person.** Robert now owns components 1
and 2, the labelling ensemble, review, training, and the export credentials; Justin owns
component 3 and runs the ingest service. That is a real single point of failure — if Robert
is unavailable for a week, everything except the web app stops.

Recorded rather than argued with: it is the team's call, and the alternative was leaving two
tasks unowned, which is worse. Worth revisiting if the critical path stalls. The cheapest
hedge is ordering: the detection pipeline first, since everything downstream is on fixtures
until it lands, and Roboflow and the trainer are useless without labels to put in them.
