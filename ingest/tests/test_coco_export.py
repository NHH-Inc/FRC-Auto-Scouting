import json
import tempfile
import unittest
from pathlib import Path

from ingest.collection.coco_export import export_coco_dataset
from ingest.collection.config import load_config


class CocoExportTests(unittest.TestCase):
    def _config(self, root: Path):
        config = root / "config.yaml"
        config.write_text(
            """season: 2026
game: REBUILT
storage: {root: data, segments: data/segments, collections: data/collections, datasets: data/datasets}
sampling: {fps: 2}
split: {seed: 1, train: 0.7, val: 0.15, test: 0.15}
classes: [{name: robot, id: 0}]
"""
        )
        return load_config(config)

    def test_export_matches_rfdetr_coco_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collection = root / "collection"
            frames = collection / "frames" / "match"
            frames.mkdir(parents=True)
            (frames / "f000000.jpg").write_bytes(b"not-decoded-in-this-test")
            (collection / "frames.jsonl").write_text(json.dumps({
                "frame_id": "frame-1", "image_path": "frames/match/f000000.jpg",
                "width": 1000, "height": 500, "split": "train",
            }) + "\n")
            (collection / "model-consensus.jsonl").write_text(json.dumps({
                "frame_id": "frame-1", "status": "proposed", "boxes": [{
                    "class_name": "robot", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4,
                }],
            }) + "\n")
            output = root / "dataset"
            report = export_coco_dataset(
                collection=collection, config=self._config(root), output=output,
                allow_unreviewed=True,
            )
            payload = json.loads((output / "train" / "_annotations.coco.json").read_text())
            self.assertEqual(report["splits"]["train"], {"images": 1, "annotations": 1})
            self.assertEqual(payload["images"][0]["file_name"], "frame-1.jpg")
            self.assertEqual(payload["annotations"][0]["bbox"], [100.0, 100.0, 300.0, 200.0])

    def test_unreviewed_labels_require_an_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collection = root / "collection"
            frames = collection / "frames" / "match"
            frames.mkdir(parents=True)
            (frames / "f.jpg").write_bytes(b"x")
            (collection / "frames.jsonl").write_text(json.dumps({
                "frame_id": "frame-1", "image_path": "frames/match/f.jpg",
                "width": 10, "height": 10, "split": "train",
            }) + "\n")
            (collection / "model-consensus.jsonl").write_text(json.dumps({
                "frame_id": "frame-1", "status": "proposed", "boxes": [],
            }) + "\n")
            with self.assertRaisesRegex(ValueError, "Refusing unreviewed"):
                export_coco_dataset(
                    collection=collection, config=self._config(root), output=root / "dataset",
                    allow_unreviewed=False,
                )
