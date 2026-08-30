# Local FRC data collection with Ollama

This workflow extracts deterministic images from an already-downloaded segment and asks three
local vision models for robot-box proposals. All model output remains `status: proposed` with
`human_review_required: true`; model agreement prioritizes review and is not ground truth.

The box policy is the full physical robot extent when it can be inferred under occlusion. Boxes
use normalized top-left `x, y, w, h` coordinates. Start with the generic `robot` class only.

## One-time setup (macOS)

```bash
brew install ffmpeg ollama
brew services start ollama
ollama pull qwen3-vl:4b
ollama pull qwen2.5vl:7b
ollama pull gemma3:4b
.venv/bin/pip install -r ingest/requirements.txt
```

The models run one at a time, so this set is suitable for a 16 GB Apple Silicon Mac. Ollama's API
stays on `127.0.0.1:11434` by default and images are not sent to a cloud service.

## Connect the repository to Ollama

Confirm that the service and models are available:

```bash
curl http://127.0.0.1:11434/api/version
ollama list
```

The collection code reads the connection and model names from the `ollama` section of the YAML:

```yaml
ollama:
  url: http://127.0.0.1:11434
  models:
    - qwen3-vl:4b
    - qwen2.5vl:7b
    - gemma3:4b
  iou_threshold: 0.40
```

`auto-label` sends each frame to the configured `/api/chat` endpoint as a base64 image with a JSON
schema for normalized robot boxes. The models are invoked sequentially and unloaded between calls,
which prevents the three model weights from competing for memory. No API key is required for the
default local connection.

SAM 3.1 is an optional, separate CUDA proposal source. It writes `sam3-proposals.jsonl` rather
than changing this three-model consensus. See [SAM3.md](SAM3.md) for Robert's separate install and
the `sam3-propose` command.

If the version check fails, start or restart the service:

```bash
brew services restart ollama
```

## Extract a collection

Copy the example configuration if you want to change its values, then run from the repository root:

```bash
cp configs/data_collection.example.yaml configs/data_collection.yaml
.venv/bin/python -m ingest.collection.cli extract \
  --segment data/segments/<segment>.mp4 \
  --match-id 2026casf_qm42 \
  --video-id <youtube-id> \
  --source-url 'https://www.youtube.com/watch?v=<youtube-id>' \
  --start-offset 120 \
  --config configs/data_collection.yaml
```

The command prints the collection directory. Rerunning the same source and configuration returns
that directory without rewriting it. Changed content or configuration cannot silently overwrite it.

## Generate and compare proposals

```bash
.venv/bin/python -m ingest.collection.cli auto-label \
  --collection data/collections/<collection-id> \
  --config configs/data_collection.yaml

.venv/bin/python -m ingest.collection.cli validate-collection \
  --collection data/collections/<collection-id>
```

`model-proposals.jsonl` preserves every model's answer. `model-consensus.jsonl` contains boxes where
at least two models overlap at the configured IoU threshold. `agreement_count` is supporting model
count and `min_pairwise_iou` measures localization consistency. `model-comparison.json` summarizes
per-model and consensus counts. A human must still correct and accept boxes before exporting training
labels. Use `--limit 1` for a quick end-to-end test.

Model-reported confidence is not calibrated across families. Use overlap only as a review-order hint,
not as proof that a box is correct. Empty consensus means the frame needs manual inspection; it does
not mean that no robot is present. The saved consensus box is one actual proposal from the
most-confident supporting model, never an average of coordinates.

## Where data is written

All generated artifacts live under `data/`, which is ignored by Git:

```text
data/
  segments/                              downloaded MP4 segments from ingest
  collections/<collection-id>/
    collection.json                      source, checksum, timestamps, and media metadata
    config.snapshot.json                 exact extraction configuration
    frames.jsonl                         frame IDs, hashes, timestamps, split, and image paths
    frames/<match-id>/*.jpg               sampled images sent to local models
    model-proposals.jsonl                 raw validated boxes from every model
    model-consensus.jsonl                 boxes supported by at least two models
    model-comparison.json                 per-model and consensus summary
    sam3-proposals.jsonl                  optional SAM 3.1 text-prompt boxes; review-only
  datasets/                              reserved for immutable reviewed dataset exports
```

The downloader owned by `ingest/` writes MP4 files to `data/segments/`. The `extract` command reads
one of those MP4 files and creates a collection. The `auto-label` command reads the collection images
and writes only proposal/comparison files back into that same collection directory.

## Which media models should use

Use the immutable downloaded MP4 in `data/segments/` for frame extraction, training, evaluation,
and repeatable offline inference. Do not build a dataset from `/api/stream/<job-id>/video` or
`/audio`: those endpoints proxy expiring YouTube URLs and exist only to make review available while
the local segment downloads. The stream and downloaded segment also use different media clocks.

Model outputs use segment-relative seconds and normalized top-left `x, y, w, h` boxes. A model
reading a full-source stream must subtract the job's `start_offset` before writing timestamps; a
model reading the downloaded segment writes its media time directly. See `media-streaming.md` for
the complete model-facing media, timing, and overlay contract.

## Where the output is used

The current implementation ends at assisted annotation proposals. It deliberately does not feed
model output directly into the C++ analyzer, web app, or detector training. The intended flow is:

```text
data/segments/<video>.mp4
  -> extract
  -> data/collections/<collection-id>/frames + manifests
  -> auto-label
  -> model-proposals.jsonl + model-consensus.jsonl
  -> human correction and acceptance
  -> reviewed annotations.jsonl
  -> RF-DETR COCO export under data/datasets/<dataset-id>/
  -> RF-DETR training and evaluation
```

Until the annotation import and dataset exporter are implemented, use `model-consensus.jsonl` to
prioritize manual review and `model-proposals.jsonl` to compare or audit individual models. Do not
rename either file to `annotations.jsonl`: reviewed annotations are a separate ground-truth artifact.

## Check whether Gemma is a real third vote

Run the normal annotation command with `--limit 50`, then open `model-comparison.json`. For each
model it records `decisive_two_model_votes`: a consensus box that would disappear if that model
were removed. If Gemma's number is consistently near zero, the two Qwen models are effectively
deciding every 2-of-3 result and Gemma is not contributing useful diversity. Keep the raw proposals
either way; this is a measurement, not a reason to silently rewrite labels.

Completed collections can be copied to the shared artifact store described in the data-collection
design plan. Preserve the entire collection directory so its checksums and provenance travel with
the images and proposals.
