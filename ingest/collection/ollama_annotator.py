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


def annotate_image(*, image: Path, model: str, url: str, timeout: float = 600) -> dict[str, Any]:
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
        "options": {"temperature": 0, "seed": 20260829},
        "keep_alive": "0",
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
    output = []
    for cluster in clusters:
        supporting_models = sorted({item["model"] for item in cluster})
        count = len(supporting_models)
        if count < 2:
            continue
        pairwise = [
            _iou(cluster[index], cluster[other])
            for index in range(len(cluster))
            for other in range(index + 1, len(cluster))
        ]
        output.append({
            "class_name": "robot",
            "x": round(sum(item["x"] for item in cluster) / len(cluster), 6),
            "y": round(sum(item["y"] for item in cluster) / len(cluster), 6),
            "w": round(sum(item["w"] for item in cluster) / len(cluster), 6),
            "h": round(sum(item["h"] for item in cluster) / len(cluster), 6),
            "confidence": round(sum(item["confidence"] for item in cluster) / len(cluster), 6),
            "supporting_models": supporting_models,
            "agreement_count": count,
            "agreement_ratio": round(count / len(models), 6),
            "min_pairwise_iou": round(min(pairwise), 6),
            "source": "model_ensemble",
            "review_status": "unreviewed",
        })
    return sorted(output, key=lambda item: (item["agreement_count"], item["confidence"]), reverse=True)


def build_consensus(collection: Path, models: list[str], threshold: float) -> Path:
    proposal_rows = _read_jsonl(collection / "model-proposals.jsonl")
    by_frame: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in proposal_rows:
        if row.get("model") in models:
            by_frame[row["frame_id"]].append(row)
    rows = []
    for frame_id, proposals in sorted(by_frame.items()):
        rows.append({
            "frame_id": frame_id,
            "annotator_version": OLLAMA_ANNOTATOR_VERSION,
            "models": models,
            "iou_threshold": threshold,
            "generated_at": _utc_now(),
            "status": "proposed",
            "human_review_required": True,
            "boxes": compare_frame_proposals(proposals, models, threshold),
        })
    output = collection / "model-consensus.jsonl"
    _write_jsonl(output, rows)
    per_model = {
        model: {
            "frames_run": sum(row.get("model") == model for row in proposal_rows),
            "boxes_proposed": sum(
                len(row.get("boxes", [])) for row in proposal_rows if row.get("model") == model
            ),
        }
        for model in models
    }
    all_boxes = [box for row in rows for box in row["boxes"]]
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
    limit: int | None = None, force: bool = False,
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
            result = annotate_image(image=image, model=model, url=url)
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
