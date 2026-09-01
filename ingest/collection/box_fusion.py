"""Fuse boxes from several detectors into one set with a calibrated confidence each.

The problem this solves: two detectors look at a frame and disagree. One is very sure about a box
nobody else saw; another is unsure about a box everyone else also found. Taking the highest
confidence wins the wrong argument -- a confident model that is confidently wrong beats three
hesitant models that are right.

So confidence here is not any single detector's number. It is recomputed from three things:

  agreement   how much total detector weight backed this box, out of all weight available
  tightness   how closely the backers agreed on where it is (mean pairwise IoU)
  strength    the weighted mean of what the backers actually reported

A box found by one source at 0.95 and a box found by three sources at 0.55 each end up ranked the
way a person would rank them, which is the behaviour that was asked for: scores shift according
to what everything else said, rather than being fixed at the moment of detection.

Source weights are not fixed either. `estimate_source_weights` scores each detector by how often
its boxes were corroborated by the others, so a detector that habitually invents boxes loses
influence over the final confidence -- and it loses it on evidence rather than on opinion.

This is weighted box fusion with a reliability prior. It is deliberately explainable: every fused
box carries the components that produced its score, so a bad number can be traced instead of
argued about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

#: Boxes overlapping by at least this much are treated as the same object. Robots in a wide field
#: shot are small, so a strict threshold splits genuine agreement into separate clusters.
DEFAULT_IOU = 0.40

#: How hard to punish a box that only one source found. 1.0 scales confidence linearly with the
#: share of weight backing it; higher values punish lone boxes harder.
AGREEMENT_EXPONENT = 1.0

#: A cluster whose members barely overlap is weak evidence even when several sources contributed,
#: so tightness is blended in rather than ignored.
TIGHTNESS_FLOOR = 0.5


@dataclass
class FusedBox:
    x: float
    y: float
    w: float
    h: float
    confidence: float
    supporting_sources: list[str] = field(default_factory=list)
    agreement: float = 0.0      # share of total source weight that backed this box
    tightness: float = 0.0      # mean pairwise IoU among the backers
    strength: float = 0.0       # weighted mean of the reported confidences
    source_confidences: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "class_name": "robot",
            "x": round(self.x, 6), "y": round(self.y, 6),
            "w": round(self.w, 6), "h": round(self.h, 6),
            "confidence": round(self.confidence, 6),
            "supporting_sources": self.supporting_sources,
            "agreement_count": len(self.supporting_sources),
            # Kept separately so a reviewer can see WHY the score came out where it did.
            "agreement": round(self.agreement, 4),
            "tightness": round(self.tightness, 4),
            "strength": round(self.strength, 4),
            "source_confidences": {k: round(v, 4) for k, v in self.source_confidences.items()},
            "source": "fused",
            "review_status": "unreviewed",
        }


def iou(a: dict, b: dict) -> float:
    left, top = max(a["x"], b["x"]), max(a["y"], b["y"])
    right = min(a["x"] + a["w"], b["x"] + b["w"])
    bottom = min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def fuse_frame(
    proposals: dict[str, list[dict]],
    source_weights: dict[str, float] | None = None,
    iou_threshold: float = DEFAULT_IOU,
) -> list[FusedBox]:
    """Fuse one frame's boxes.

    ``proposals`` maps a source name to its boxes; each box needs x/y/w/h and confidence.
    A source contributes at most once to a cluster -- two boxes from the same detector are two
    objects to that detector, and letting both join would manufacture agreement from one opinion.
    """
    weights = source_weights or {}
    total_weight = sum(weights.get(name, 1.0) for name in proposals) or 1.0

    # Seed clusters from the most confident boxes first, so a cluster forms around its strongest
    # member rather than around whichever box happened to be enumerated first.
    flat = [
        dict(box, _source=name)
        for name, boxes in proposals.items()
        for box in boxes
    ]
    flat.sort(key=lambda b: -float(b.get("confidence", 0.0)))

    clusters: list[list[dict]] = []
    for box in flat:
        placed = False
        for cluster in clusters:
            if any(m["_source"] == box["_source"] for m in cluster):
                continue
            if max(iou(box, m) for m in cluster) >= iou_threshold:
                cluster.append(box)
                placed = True
                break
        if not placed:
            clusters.append([box])

    fused: list[FusedBox] = []
    for cluster in clusters:
        names = sorted({m["_source"] for m in cluster})
        w = [weights.get(m["_source"], 1.0) * max(1e-6, float(m.get("confidence", 0.0)))
             for m in cluster]
        wsum = sum(w) or 1e-6

        # Coordinates are a confidence-weighted mean, which pulls the fused box toward the
        # detectors that were both trusted and sure.
        x = sum(m["x"] * wi for m, wi in zip(cluster, w)) / wsum
        y = sum(m["y"] * wi for m, wi in zip(cluster, w)) / wsum
        bw = sum(m["w"] * wi for m, wi in zip(cluster, w)) / wsum
        bh = sum(m["h"] * wi for m, wi in zip(cluster, w)) / wsum

        backing = sum(weights.get(n, 1.0) for n in names)
        agreement = min(1.0, backing / total_weight)

        pairs = [iou(cluster[i], cluster[j])
                 for i in range(len(cluster)) for j in range(i + 1, len(cluster))]
        tightness = sum(pairs) / len(pairs) if pairs else 1.0

        strength = sum(float(m.get("confidence", 0.0)) * wi for m, wi in zip(cluster, w)) / wsum

        # Blend rather than multiply tightness straight in: a single-source box has no pairwise
        # IoU to measure, and should not be rewarded with a perfect tightness of 1.0.
        tightness_factor = TIGHTNESS_FLOOR + (1.0 - TIGHTNESS_FLOOR) * (tightness if pairs else 0.0)
        confidence = strength * (agreement ** AGREEMENT_EXPONENT) * tightness_factor

        fused.append(FusedBox(
            x=x, y=y, w=bw, h=bh,
            confidence=max(0.0, min(1.0, confidence)),
            supporting_sources=names,
            agreement=agreement,
            tightness=tightness if pairs else 0.0,
            strength=strength,
            source_confidences={m["_source"]: float(m.get("confidence", 0.0)) for m in cluster},
        ))

    fused.sort(key=lambda b: -b.confidence)
    return fused


def estimate_source_weights(
    frames: Iterable[dict[str, list[dict]]],
    iou_threshold: float = DEFAULT_IOU,
) -> dict[str, float]:
    """Score each source by how often the others corroborated it.

    A detector whose boxes nobody else finds is either seeing something real that others miss, or
    inventing things. Across enough frames the second is far more common, so corroboration rate is
    a usable reliability proxy -- and it is measured from the data rather than assumed.

    Returns weights normalised so the mean is 1.0, keeping fused confidences on a familiar scale.
    """
    found: dict[str, int] = {}
    backed: dict[str, int] = {}

    for proposals in frames:
        names = list(proposals)
        for name in names:
            found.setdefault(name, 0)
            backed.setdefault(name, 0)
        for name, boxes in proposals.items():
            others = [(o, b) for o in names if o != name for b in proposals[o]]
            for box in boxes:
                found[name] += 1
                if any(iou(box, other) >= iou_threshold for _, other in others):
                    backed[name] += 1

    if not found:
        return {}

    rates = {n: (backed[n] / found[n] if found[n] else 0.0) for n in found}
    # Floor at 0.1 so a bad source is demoted rather than silenced -- being outvoted on this
    # dataset is not proof it is useless on the next one.
    scores = {n: max(0.1, r) for n, r in rates.items()}
    mean = sum(scores.values()) / len(scores)
    return {n: s / mean for n, s in scores.items()}
