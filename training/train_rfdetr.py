"""Fine-tune and export the one-class FRC robot detector on an NVIDIA CUDA machine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="COCO dataset root; must contain train/_annotations.coco.json")
    parser.add_argument("--output", required=True, help="directory for checkpoints and exported ONNX")
    parser.add_argument("--variant", choices=("nano", "small", "medium"), default="small")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", default="auto", help='RF-DETR batch size, or "auto" (default)')
    parser.add_argument("--grad-accum-steps", type=int, default=1)
    parser.add_argument("--resolution", type=int, default=640)
    parser.add_argument(
        "--augmentation",
        choices=("conservative", "none"),
        default="conservative",
        help="conservative = flip + mild image variation; none = RF-DETR resize pipeline only",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = Path(args.dataset)
    for split in ("train", "valid"):
        annotations = dataset / split / "_annotations.coco.json"
        if not annotations.is_file():
            raise SystemExit(f"Dataset is not RF-DETR COCO format: missing {split}/_annotations.coco.json")
        try:
            image_count = len(json.loads(annotations.read_text(encoding="utf-8")).get("images", []))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Dataset has invalid COCO JSON: {annotations}") from exc
        if image_count == 0:
            raise SystemExit(
                f"Dataset has no {split} images. Export several match collections; a match stays in one split."
            )
    if args.resolution <= 0 or args.resolution % 32:
        raise SystemExit("--resolution must be a positive multiple of 32")
    try:
        import torch
        from rfdetr import RFDETRMedium, RFDETRNano, RFDETRSmall
        from rfdetr.datasets.aug_configs import AUG_CONSERVATIVE
    except ImportError as exc:
        raise SystemExit("Install training\\requirements-rfdetr.txt in a separate training venv first") from exc
    if not torch.cuda.is_available():
        raise SystemExit("RF-DETR training requires Robert's NVIDIA CUDA machine; CUDA was not detected")

    variants = {"nano": RFDETRNano, "small": RFDETRSmall, "medium": RFDETRMedium}
    batch_size: int | str = int(args.batch_size) if args.batch_size.isdigit() else args.batch_size
    if batch_size != "auto" and (not isinstance(batch_size, int) or batch_size <= 0):
        raise SystemExit("--batch-size must be a positive integer or auto")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    # Broadcast footage gains from lighting/compression variation, but robots never appear
    # upside down or rotated 45 degrees. The upstream conservative preset stays inside that
    # realistic envelope (horizontal flip + mild brightness/contrast), while RF-DETR keeps its
    # standard resize/scale-jitter pipeline. It also transforms boxes with the image.
    aug_config = AUG_CONSERVATIVE if args.augmentation == "conservative" else {}
    model = variants[args.variant]()
    model.train(
        dataset_dir=str(dataset), output_dir=str(output), epochs=args.epochs,
        batch_size=batch_size, grad_accum_steps=args.grad_accum_steps,
        resolution=args.resolution, run_test=True, aug_config=aug_config,
    )
    (output / "training-config.json").write_text(
        json.dumps({
            "variant": args.variant,
            "epochs": args.epochs,
            "batch_size": batch_size,
            "resolution": args.resolution,
            "augmentation": args.augmentation,
            "augmentation_detail": (
                "RF-DETR AUG_CONSERVATIVE (horizontal flip and mild pixel variation)"
                if args.augmentation == "conservative" else "disabled"
            ),
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    export_dir = output / "onnx"
    model.export(output_dir=str(export_dir), shape=(args.resolution, args.resolution))
    print(export_dir / "inference_model.onnx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
