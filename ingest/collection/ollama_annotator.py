"""Local Ollama vision proposals and cross-model agreement scoring."""

from __future__ import annotations

import base64
import json
import math
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import OLLAMA_ANNOTATOR_VERSION

#: Fixed so a rerun reproduces byte-for-byte. The retry uses DEFAULT_SEED + 1, which is still
#: deterministic -- a second fixed draw, not randomness.
DEFAULT_SEED = 20260829


BOX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "boxes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "class_name": {"type": "string", "enum": ["robot"]},
                    "x": {"type": "number", "minimum": 0, "maximum": 1},
                    "y": {"type": "number", "minimum": 0, "maximum": 1},
                    "w": {"type": "number", "minimum": 0, "maximum": 1},
                    "h": {"type": "number", "minimum": 0, "maximum": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "team": {"type": ["integer", "null"]},
                },
                "required": ["class_name", "x", "y", "w", "h", "confidence", "team"],
            },
        },
        "quality_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["boxes", "quality_flags"],
}

PROMPT = """Detect every complete or partially visible FRC competition robot in this image.
Return tight boxes around the full physical robot extent when inferable under occlusion. Do not
box people, field elements, score overlays, or printed pictures. Coordinates must be normalized
top-left x, y, width, height in the range 0..1. Team is an integer only when the bumper number is
clearly readable; otherwise null. Use quality_flags from replay_closeup, camera_cut,
unreadable_frame when applicable. Return only data matching this JSON schema: {schema}"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    temporary.replace(path)


def list_installed_models(url: str) -> dict[str, str | None]:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=5) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Ollama is not reachable at {url}: {exc}") from exc
    return {item["name"]: item.get("digest") for item in payload.get("models", [])}


def _validate_boxes(value: dict[str, Any]) -> list[dict[str, Any]]:
    boxes = []
    for box in value.get("boxes", []):
        try:
            x, y, w, h = (float(box[key]) for key in ("x", "y", "w", "h"))
            confidence = float(box["confidence"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(item) for item in (x, y, w, h, confidence)):
            continue
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
            continue
        boxes.append({
            "class_name": "robot",
            "team": box.get("team") if isinstance(box.get("team"), int) else None,
            "x": round(x, 6), "y": round(y, 6), "w": round(w, 6), "h": round(h, 6),
            "confidence": round(max(0.0, min(1.0, confidence)), 6),
            "source": "model",
        })
    return boxes


def annotate_image(
    *,
    image: Path,
    model: str,
    url: str,
    timeout: float = 600,
    keep_alive: str = "0",
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Ask one model for robot boxes on one frame.

    ``keep_alive`` is how long Ollama holds the weights in memory after answering. The default
    "0" unloads immediately, which is right on a 16 GB Mac where three sets of weights would
    otherwise compete for memory -- the reason this was hardcoded originally.

    It is badly wrong on a machine with room for all three at once. Unloading after every frame
    makes each frame pay three model loads, and a load costs far more than the inference does
    (~12s versus ~2-3s here), so a run takes roughly four times longer than it needs to. Set
    ``ollama.keep_alive`` in the collection config on such a machine. Model output is unchanged
    either way: this only controls residency, not sampling, which stays temperature 0 with a
    fixed seed.
    """
    request_body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": PROMPT.format(schema=json.dumps(BOX_SCHEMA, separators=(",", ":"))),
            "images": [base64.b64encode(image.read_bytes()).decode()],
        }],
        "stream": False,
        "think": False,
        "format": BOX_SCHEMA,
        "options": {"temperature": 0, "seed": seed},
        "keep_alive": keep_alive,
    }
    request = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps(request_body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            api_result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Ollama rejected {model}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Ollama request for {model} failed: {exc}") from exc
    message = api_result.get("message", {})
    raw = message.get("content") or message.get("thinking", "")
    response_channel = "content" if message.get("content") else "thinking"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{model} returned invalid JSON: {raw[:300]}") from exc
    return {
        "boxes": _validate_boxes(parsed),
        "quality_flags": [str(item) for item in parsed.get("quality_flags", [])],
        "raw_response": raw,
        "response_channel": response_channel,
        "total_duration_ns": api_result.get("total_duration"),
        "prompt_eval_count": api_result.get("prompt_eval_count"),
        "eval_count": api_result.get("eval_count"),
    }


def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    left, top = max(a["x"], b["x"]), max(a["y"], b["y"])
    right = min(a["x"] + a["w"], b["x"] + b["w"])
    bottom = min(a["y"] + a["h"], b["y"] + b["h"])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = a["w"] * a["h"] + b["w"] * b["h"] - intersection
    return intersection / union if union else 0.0


def compare_frame_proposals(
    proposals: list[dict[str, Any]], models: list[str], threshold: float
) -> list[dict[str, Any]]:
    candidates = [
        dict(box, model=row["model"])
        for row in proposals
        for box in row.get("boxes", [])
    ]
    clusters: list[list[dict[str, Any]]] = []
    for candidate in sorted(candidates, key=lambda item: item["confidence"], reverse=True):
        best_cluster = None
        best_score = threshold
        for cluster in clusters:
            if candidate["model"] in {item["model"] for item in cluster}:
                continue
            score = max(_iou(candidate, item) for item in cluster)
            if score >= best_score:
                best_cluster, best_score = cluster, score
        (best_cluster if best_cluster is not None else clusters.append([candidate]))
        if best_cluster is not None:
            best_cluster.append(candidate)
    # With a single model there is nothing to agree with, so requiring two supporters would drop
    # every box and write an empty consensus file -- silently, with no error, which is exactly how
    # a reviewer ends up staring at blank frames. Pass the boxes through instead, marked honestly
    # as single-model, and let the caller decide what an unverified proposal is worth.
    single_model = len({row["model"] for row in proposals}) < 2
    minimum_support = 1 if single_model else 2

    output = []
    for cluster in clusters:
        supporting_models = sorted({item["model"] for item in cluster})
        count = len(supporting_models)
        if count < minimum_support:
            continue
        # Agreement decides whether a cluster survives. It does NOT average coordinates: a
        # missing or badly localized proposal would drag an averaged box onto empty carpet.
        # Keep a real proposal (the most confident member) as the representative instead.
        representative = max(cluster, key=lambda item: item["confidence"])
        pairwise = [
            _iou(cluster[index], cluster[other])
            for index in range(len(cluster))
            for other in range(index + 1, len(cluster))
        ]
        output.append({
            "class_name": "robot",
            "x": representative["x"],
            "y": representative["y"],
            "w": representative["w"],
            "h": representative["h"],
            "confidence": representative["confidence"],
            "representative_model": representative["model"],
            "supporting_models": supporting_models,
            "agreement_count": count,
            "agreement_ratio": round(count / len(models), 6) if models else 0.0,
            # A one-member cluster has no pairs to compare, so there is no agreement to report.
            # None says that; 0.0 would read as "they disagreed completely", which is a different
            # and much more damning claim.
            "min_pairwise_iou": round(min(pairwise), 6) if pairwise else None,
            # Do not call one model an ensemble. Downstream this is the difference between a
            # corroborated box and one model's guess.
            "source": "model_single" if single_model else "model_ensemble",
            "review_status": "unreviewed",
        })
    return sorted(output, key=lambda item: (item["agreement_count"], item["confidence"]), reverse=True)


def build_consensus(collection: Path, models: list[str], threshold: float) -> Path:
    proposal_rows = _read_jsonl(collection / "model-proposals.jsonl")
    by_frame: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in proposal_rows:
        # A failed row means "this model gave no answer", which is not the same claim as "this
        # model saw no robots". Counting it as the latter would let a repetition-loop failure
        # vote against boxes the other two models agree on.
        if row.get("model") in models and row.get("status") != "failed":
            by_frame[row["frame_id"]].append(row)
    rows = []
    for frame_id, proposals in sorted(by_frame.items()):
        answered = [row["model"] for row in proposals]
        rows.append({
            "frame_id": frame_id,
            "annotator_version": OLLAMA_ANNOTATOR_VERSION,
            "models": models,
            # Which models actually answered for this frame. Where this is shorter than `models`,
            # agreement counts came from a smaller panel and mean correspondingly less.
            "responding_models": answered,
            "iou_threshold": threshold,
            "generated_at": _utc_now(),
            "status": "proposed",
            "human_review_required": True,
            "boxes": compare_frame_proposals(proposals, answered, threshold),
        })
    output = collection / "model-consensus.jsonl"
    _write_jsonl(output, rows)

    # An empty consensus built from non-empty proposals is the failure mode that wastes a whole
    # review session: export-coco reads this file, so it would hand a reviewer hundreds of frames
    # with no boxes on them and no indication anything went wrong.
    proposed_boxes = sum(
        len(row.get("boxes", [])) for row in proposal_rows if row.get("status") != "failed"
    )
    kept_boxes = sum(len(row["boxes"]) for row in rows)
    if proposed_boxes and not kept_boxes:
        print(
            f"WARNING: {proposed_boxes} proposed boxes produced 0 consensus boxes. Every cluster "
            f"fell below the agreement bar (iou_threshold={threshold}, models={models}). "
            "export-coco reads this file, so the dataset would have no labels at all.",
            flush=True,
        )
    all_boxes = [box for row in rows for box in row["boxes"]]
    per_model = {
        model: {
            "frames_run": sum(row.get("model") == model for row in proposal_rows),
            # A model that fails often is not contributing a reliable vote, however good its
            # answers look when it does respond.
            "frames_failed": sum(
                row.get("model") == model and row.get("status") == "failed"
                for row in proposal_rows
            ),
            "boxes_proposed": sum(
                len(row.get("boxes", [])) for row in proposal_rows if row.get("model") == model
            ),
            # This consensus box would disappear if this model were removed.
            "decisive_two_model_votes": sum(
                model in box["supporting_models"] and box["agreement_count"] == 2
                for box in all_boxes
            ),
            "consensus_boxes_supported": sum(model in box["supporting_models"] for box in all_boxes),
            "representative_boxes": sum(box["representative_model"] == model for box in all_boxes),
        }
        for model in models
    }
    summary = {
        "annotator_version": OLLAMA_ANNOTATOR_VERSION,
        "generated_at": _utc_now(),
        "models": models,
        "iou_threshold": threshold,
        "frames_with_any_proposals": len(by_frame),
        "per_model": per_model,
        "consensus_boxes": len(all_boxes),
        "unanimous_boxes": sum(box["agreement_count"] == len(models) for box in all_boxes),
        "frames_with_consensus": sum(bool(row["boxes"]) for row in rows),
        "how_to_read_this": (
            "Compare decisive_two_model_votes across models on a 50-frame run. A low value for "
            "one model means it rarely changes a 2-of-3 consensus and is not adding a real vote."
        ),
        "human_review_required": True,
        "warning": "Model agreement is a review-priority signal, not ground-truth verification.",
    }
    comparison_path = collection / "model-comparison.json"
    temporary = comparison_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    temporary.replace(comparison_path)
    return output


def annotate_collection(
    *, collection: Path, models: list[str], url: str, threshold: float,
    limit: int | None = None, force: bool = False, keep_alive: str = "0",
) -> tuple[Path, Path]:
    frame_rows = _read_jsonl(collection / "frames.jsonl")
    if limit is not None:
        frame_rows = frame_rows[:limit]
    installed = list_installed_models(url)
    missing = [model for model in models if model not in installed]
    if missing:
        raise RuntimeError("Ollama models are not installed: " + ", ".join(missing))
    output = collection / "model-proposals.jsonl"
    rows = _read_jsonl(output)
    targets = {(frame["frame_id"], model) for frame in frame_rows for model in models}
    if force:
        rows = [row for row in rows if (row["frame_id"], row["model"]) not in targets]
    existing = {(row["frame_id"], row["model"]) for row in rows}
    for frame in frame_rows:
        image = collection / frame["image_path"]
        for model in models:
            key = (frame["frame_id"], model)
            if key in existing:
                continue
            print(f"{frame['frame_id']}: running {model}", flush=True)
            result = None
            last_error: RuntimeError | None = None
            # A repetition loop is a sampling accident, not a property of the image: the model
            # locks onto one box and repeats it until the token limit truncates the JSON. A
            # different seed usually breaks the loop, and one retry recovered most failures in
            # practice. Seeds are fixed and derived, so a rerun still reproduces exactly.
            for attempt, attempt_seed in enumerate((DEFAULT_SEED, DEFAULT_SEED + 1)):
                try:
                    result = annotate_image(
                        image=image, model=model, url=url,
                        keep_alive=keep_alive, seed=attempt_seed,
                    )
                    if attempt:
                        print(f"{frame['frame_id']}: {model} recovered on retry", flush=True)
                    break
                except RuntimeError as exc:
                    last_error = exc
            if result is None:
                exc = last_error
                # One model failing one frame must not end the run. Vision models fall into
                # repetition loops -- emitting the same box until they hit the token limit, which
                # truncates the JSON mid-object -- and that is a property of the model, not a bug
                # we can fix here. Letting it propagate threw away every frame already labelled in
                # this collection and every frame after it.
                #
                # The ensemble is the reason this is safe: three models vote, so a frame with two
                # answers is still usable. Record the failure as a row so it stays visible in the
                # data rather than becoming a silent hole, and carry on.
                print(f"{frame['frame_id']}: {model} FAILED: {str(exc)[:160]}", flush=True)
                rows.append({
                    "frame_id": frame["frame_id"],
                    "model": model,
                    "model_digest": installed[model],
                    "annotator_version": OLLAMA_ANNOTATOR_VERSION,
                    "generated_at": _utc_now(),
                    "status": "failed",
                    "human_review_required": True,
                    "error": str(exc)[:500],
                    "boxes": [],
                })
                rows.sort(key=lambda row: (row["frame_id"], row["model"]))
                _write_jsonl(output, rows)
                continue
            rows.append({
                "frame_id": frame["frame_id"],
                "model": model,
                "model_digest": installed[model],
                "annotator_version": OLLAMA_ANNOTATOR_VERSION,
                "generated_at": _utc_now(),
                "status": "proposed",
                "human_review_required": True,
                **result,
            })
            rows.sort(key=lambda row: (row["frame_id"], row["model"]))
            _write_jsonl(output, rows)
            print(f"{frame['frame_id']}: {model} proposed {len(result['boxes'])} boxes", flush=True)
    consensus = build_consensus(collection, models, threshold)
    return output, consensus
