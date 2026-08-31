"""Disk guards and segment retention.

Doc 2: "Downloaded media is a cache, not a record... Set a retention policy early or disk usage
will get out of hand fast, since a single event's footage is tens of gigabytes."

DECISIONS D9 settled that policy months before anything implemented it, which is how a 9.2 GB
unclipped VOD ended up sitting on disk indefinitely.
"""

import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from ingest import models, retention  # noqa: E402
from ingest.downloader import free_gb, require_free_space  # noqa: E402


class DiskGuardTests(unittest.TestCase):
    def test_reports_free_space_for_a_real_path(self):
        self.assertGreater(free_gb("."), 0)

    def test_walks_up_to_a_parent_that_exists(self):
        # The download directory may not exist yet on a first run.
        missing = Path(tempfile.gettempdir()) / "frc-does-not-exist" / "nor-this"
        self.assertGreater(free_gb(missing), 0)

    def test_refuses_a_request_the_disk_cannot_hold(self):
        with self.assertRaises(RuntimeError) as caught:
            require_free_space(".", need_gb=10_000_000)
        # The message has to say what to do, not just that it failed.
        self.assertIn("free", str(caught.exception).lower())

    def test_allows_a_reasonable_request(self):
        # Pin the floor instead of trusting the machine to have MIN_FREE_GB spare. Otherwise this
        # asserts something about the runner rather than about the function, and fails on a CI box
        # that happens to be low on scratch space.
        with patch("ingest.downloader.MIN_FREE_GB", 0.0):
            require_free_space(".", need_gb=0.001)

    def test_refuses_when_the_floor_is_above_free_space(self):
        # The floor applies even when the caller asks for almost nothing.
        with patch("ingest.downloader.MIN_FREE_GB", 10_000_000.0):
            with self.assertRaises(RuntimeError):
                require_free_space(".", need_gb=0.001)


class _FakeQuery:
    def __init__(self, jobs):
        self._jobs = jobs

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._jobs


class _FakeDb:
    def __init__(self, jobs):
        self._jobs = jobs
        self.committed = False

    def query(self, _model):
        return _FakeQuery(self._jobs)

    def commit(self):
        self.committed = True


def _job(path, days_old, status="complete"):
    job = models.Job()
    job.job_id = f"job-{days_old}"
    job.status = status
    job.local_path = str(path) if path else None
    job.updated_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_old)
    return job


class RetentionTests(unittest.TestCase):
    def test_deletes_segments_past_the_grace_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old.mp4"
            old.write_bytes(b"x" * 2048)
            db = _FakeDb([_job(old, days_old=30)])

            result = retention.sweep(db, grace_days=7)

            self.assertFalse(old.exists())
            self.assertEqual(result["jobs"], 1)
            self.assertTrue(db.committed)

    def test_keeps_segments_inside_the_grace_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "fresh.mp4"
            fresh.write_bytes(b"x" * 2048)
            db = _FakeDb([_job(fresh, days_old=1)])

            result = retention.sweep(db, grace_days=7)

            self.assertTrue(fresh.exists(), "a segment inside the grace window must survive")
            self.assertEqual(result["jobs"], 0)

    def test_clears_local_path_so_the_job_stops_pointing_at_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old.mp4"
            old.write_bytes(b"x")
            job = _job(old, days_old=30)
            retention.sweep(_FakeDb([job]), grace_days=7)

            # The job survives -- its events are the product. Only the cache pointer goes.
            self.assertIsNone(job.local_path)

    def test_dry_run_reports_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old.mp4"
            old.write_bytes(b"x" * 4096)
            db = _FakeDb([_job(old, days_old=30)])

            result = retention.sweep(db, grace_days=7, dry_run=True)

            self.assertTrue(old.exists(), "dry run must not delete")
            self.assertEqual(result["jobs"], 1)
            self.assertFalse(db.committed)

    def test_ignores_a_job_whose_file_is_already_gone(self):
        job = _job(Path(tempfile.gettempdir()) / "frc-not-here.mp4", days_old=30)
        result = retention.sweep(_FakeDb([job]), grace_days=7)
        self.assertEqual(result["jobs"], 0)
        self.assertIsNone(job.local_path)


if __name__ == "__main__":
    unittest.main()
