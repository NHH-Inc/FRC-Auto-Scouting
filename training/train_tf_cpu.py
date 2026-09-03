"""Train a one-class FRC robot detector with TensorFlow on an ordinary CPU.

The input is this repository's reviewed COCO layout: train/_annotations.coco.json and
valid/_annotations.coco.json. The saved .keras model is separate from the ONNX production path.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="COCO dataset root")
    parser.add_argument("--output", required=True, help="new directory for Keras artifacts")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--resolution", type=int, default=416, choices=(320, 416, 512, 640))
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument(
        "--device", choices=("cpu", "auto"), default="cpu",
        help="cpu disables accelerators; auto uses a supported TensorFlow accelerator when available",
    )
    return parser.parse_args()


def read_coco_split(dataset: Path, split: str) -> tuple[list[str], list[list[list[float]]], list[list[float]]]:
    root = dataset / split
    annotation_path = root / "_annotations.coco.json"
    if not annotation_path.is_file():
        raise SystemExit(f"Dataset is missing {annotation_path}")
    try:
        payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid COCO JSON: {annotation_path}") from exc
    categories = {int(item["id"]): str(item["name"]) for item in payload.get("categories", [])}
    if set(categories.values()) != {"robot"}:
        raise SystemExit("TensorFlow baseline accepts exactly one COCO category named 'robot'")
    robot_ids = {category_id for category_id, name in categories.items() if name == "robot"}
    images = {int(item["id"]): item for item in payload.get("images", [])}
    boxes_by_image: dict[int, list[list[float]]] = defaultdict(list)
    for annotation in payload.get("annotations", []):
        if int(annotation.get("category_id", -1)) not in robot_ids or int(annotation.get("iscrowd", 0)):
            continue
        x, y, width, height = (float(value) for value in annotation["bbox"])
        if width > 0.0 and height > 0.0:
            boxes_by_image[int(annotation["image_id"])].append([x, y, x + width, y + height])
    paths: list[str] = []
    boxes: list[list[list[float]]] = []
    labels: list[list[float]] = []
    for image_id, image in sorted(images.items()):
        path = root / str(image["file_name"])
        if not path.is_file():
            raise SystemExit(f"COCO image is missing: {path}")
        image_boxes = boxes_by_image[image_id]
        paths.append(str(path))
        boxes.append(image_boxes)
        labels.append([0.0] * len(image_boxes))
    if not paths:
        raise SystemExit(f"Dataset has no images in {split}")
    if not any(boxes):
        raise SystemExit(f"Dataset has no robot annotations in {split}")
    return paths, boxes, labels


def build_dataset(paths, boxes, labels, *, batch_size: int, resolution: int, training: bool):
    import tensorflow as tf
    import keras_cv
    source = tf.data.Dataset.from_tensor_slices((
        tf.constant(paths), tf.ragged.constant(boxes, dtype=tf.float32, ragged_rank=1),
        tf.ragged.constant(labels, dtype=tf.float32, ragged_rank=1),
    ))

    def load(path, image_boxes, classes):
        image = tf.io.decode_image(tf.io.read_file(path), channels=3, expand_animations=False)
        image.set_shape([None, None, 3])
        return {"images": tf.cast(image, tf.float32), "bounding_boxes": {"boxes": image_boxes, "classes": classes}}

    resize = keras_cv.layers.JitteredResize(
        target_size=(resolution, resolution), scale_factor=(0.8, 1.2) if training else (1.0, 1.0),
        bounding_box_format="xyxy",
    )
    data = source.map(load, num_parallel_calls=tf.data.AUTOTUNE)
    if training:
        data = data.shuffle(min(len(paths), max(32, batch_size * 8)), reshuffle_each_iteration=True)
    data = data.ragged_batch(batch_size, drop_remainder=False)
    if training:
        data = data.map(keras_cv.layers.RandomFlip(mode="horizontal", bounding_box_format="xyxy"), num_parallel_calls=tf.data.AUTOTUNE)
    data = data.map(resize, num_parallel_calls=tf.data.AUTOTUNE)
    return data.map(lambda item: (item["images"], item["bounding_boxes"]), num_parallel_calls=tf.data.AUTOTUNE).prefetch(tf.data.AUTOTUNE)


def main() -> int:
    args = parse_args()
    if args.epochs <= 0 or args.batch_size <= 0 or args.learning_rate <= 0:
        raise SystemExit("epochs, batch-size, and learning-rate must be positive")
    if args.device == "cpu":
        # TensorFlow reads this before import, so CPU runs remain portable and reproducible.
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    import tensorflow as tf
    import keras_cv
    if args.device == "cpu":
        tf.config.set_visible_devices([], "GPU")
    dataset = Path(args.dataset)
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    train = read_coco_split(dataset, "train")
    valid = read_coco_split(dataset, "valid")
    train_data = build_dataset(*train, batch_size=args.batch_size, resolution=args.resolution, training=True)
    valid_data = build_dataset(*valid, batch_size=args.batch_size, resolution=args.resolution, training=False)
    backbone = keras_cv.models.YOLOV8Backbone.from_preset("yolo_v8_xs_backbone_coco")
    model = keras_cv.models.YOLOV8Detector(num_classes=1, bounding_box_format="xyxy", backbone=backbone, fpn_depth=1)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=args.learning_rate, global_clipnorm=10.0),
        classification_loss="binary_crossentropy", box_loss="ciou",
    )
    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(filepath=str(output / "best.keras"), monitor="val_loss", mode="min", save_best_only=True),
        tf.keras.callbacks.CSVLogger(str(output / "history.csv")),
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=8, restore_best_weights=True),
    ]
    model.fit(train_data, validation_data=valid_data, epochs=args.epochs, callbacks=callbacks)
    model.save(output / "final.keras")
    (output / "training-config.json").write_text(json.dumps({
        "framework": "tensorflow-cpu + keras-cv", "architecture": "YOLOv8 XS detector", "classes": ["robot"],
        "epochs_requested": args.epochs, "batch_size": args.batch_size, "resolution": args.resolution,
        "learning_rate": args.learning_rate, "device": args.device, "dataset": str(dataset),
        "serving_note": "Keras model; analysis/ currently only consumes the RF-DETR ONNX output contract.",
    }, indent=2) + "\n", encoding="utf-8")
    print(output / "best.keras")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
