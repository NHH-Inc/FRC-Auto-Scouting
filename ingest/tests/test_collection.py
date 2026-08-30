import tempfile
import unittest
from pathlib import Path

from ingest.collection.ollama_annotator import compare_frame_proposals
from ingest.collection.provenance import sha256_file


class CollectionTests(unittest.TestCase):
    def test_sha256_file_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value"
            path.write_bytes(b"frc")
            self.assertEqual(
                sha256_file(path),
                "sha256:17a20d30b79a9180152bdf825c97ff52f40600395bd0f929a48feaae4f9443f1",
            )

    def test_consensus_requires_two_models(self):
        proposals = [
            {"model": "a", "boxes": [{"x": .1, "y": .1, "w": .2, "h": .2, "confidence": .8}]},
            {"model": "b", "boxes": [{"x": .11, "y": .1, "w": .2, "h": .2, "confidence": .7}]},
            {"model": "c", "boxes": [{"x": .7, "y": .7, "w": .1, "h": .1, "confidence": .9}]},
        ]
        result = compare_frame_proposals(proposals, ["a", "b", "c"], .5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["agreement_count"], 2)
        self.assertEqual(result[0]["representative_model"], "a")
        self.assertEqual(result[0]["x"], .1)
        self.assertTrue(result[0]["human_review_required"] if "human_review_required" in result[0] else True)


if __name__ == "__main__":
    unittest.main()
