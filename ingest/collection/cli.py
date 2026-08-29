"""Command-line entry point for local FRC data collection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .extractor import extract_collection
from .ollama_annotator import annotate_collection, build_consensus
from .validate import validate_collection


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="extract deterministic frames and manifests")
    extract.add_argument("--segment", required=True)
    extract.add_argument("--match-id", required=True)
    extract.add_argument("--video-id", required=True)
    extract.add_argument("--source-url", default="")
    extract.add_argument("--start-offset", type=float, default=0)
    extract.add_argument("--config", required=True)
    extract.add_argument("--collection-id")
    extract.add_argument("--job-id")

    annotate = commands.add_parser("auto-label", help="generate local multi-model proposals")
    annotate.add_argument("--collection", required=True)
    annotate.add_argument("--config", required=True)
    annotate.add_argument("--models", nargs="+")
    annotate.add_argument("--limit", type=int)
    annotate.add_argument("--force", action="store_true")

    compare = commands.add_parser("compare-models", help="rebuild IoU consensus from proposals")
    compare.add_argument("--collection", required=True)
    compare.add_argument("--config", required=True)
    compare.add_argument("--models", nargs="+")

    validate = commands.add_parser("validate-collection", help="validate collection integrity")
    validate.add_argument("--collection", required=True)
    validate.add_argument("--no-hashes", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "extract":
        config = load_config(args.config)
        path = extract_collection(
            segment=args.segment, match_id=args.match_id, video_id=args.video_id,
            source_url=args.source_url, start_offset=args.start_offset, config=config,
            collection_id=args.collection_id, job_id=args.job_id,
        )
        print(path)
        return 0
    if args.command == "auto-label":
        config = load_config(args.config)
        models = args.models or list(config.models)
        proposals, consensus = annotate_collection(
            collection=Path(args.collection), models=models, url=config.ollama_url,
            threshold=config.iou_threshold, limit=args.limit, force=args.force,
        )
        print(json.dumps({"proposals": str(proposals), "consensus": str(consensus)}))
        return 0
    if args.command == "compare-models":
        config = load_config(args.config)
        models = args.models or list(config.models)
        print(build_consensus(Path(args.collection), models, config.iou_threshold))
        return 0
    report = validate_collection(args.collection, verify_hashes=not args.no_hashes)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
