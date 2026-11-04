"""Offline tests: permanent SubHub tracker is read-only and follows live job.

No access to real GPU, Ollama, media or household SQLite.
"""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools import subhub_live_tracker as t


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "jobs.sqlite3"
        with sqlite3.connect(self.db) as db:
            db.executescript("""
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY, status TEXT, source_cues INTEGER,
                    updated TEXT, last_error TEXT, source_sha TEXT, video TEXT,
                    created TEXT
                );
                CREATE TABLE cues (
                    job_id TEXT, cue_id INTEGER, japanese TEXT, failed INTEGER
                );
            """)
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                ("daily-new-translation", "translating", 3, "latest", "",
                 "a"*64, "/srv/media/new.mkv", "2026-11-04T09:00:00"))
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                ("daily-old-pending", "queued", 2, "older", "",
                 "b"*64, "/srv/media/older.mkv", "2026-11-04T08:00:00"))
            db.executemany(
                "INSERT INTO cues VALUES (?,?,?,?)", [
                    ("daily-new-translation", 1, "はい", 0),
                    ("daily-new-translation", 2, None, 0),
                    ("daily-new-translation", 3, None, 0),
                    ("daily-old-pending", 1, None, 0),
                    ("daily-old-pending", 2, None, 0),
                ])
            db.commit()

    def test_select_active_worker_over_pending_queue(self):
        with patch.object(t, "active_worker_job",
                          return_value="daily-new-translation"):
            row = t.checkpoint(self.db)
        self.assertEqual(row["id"], "daily-new-translation")
        self.assertEqual(row["completed"], 1)
        self.assertEqual(row["total"], 3)
        self.assertEqual(row["title"], "new")
        self.assertEqual(row["source_sha"], "a"*64)

    def test_prefer_explicit_job_id(self):
        with patch.object(t, "active_worker_job",
                          side_effect=AssertionError("must not scan processes")):
            row = t.checkpoint(self.db, "daily-old-pending")
        self.assertEqual(row["id"], "daily-old-pending")

    def test_active_job_process_parser(self):
        processes = """
python3 /usr/bin/python3 /home/optiplex/bruiser-pilot/subhub-control/daily_worker.py --root /tmp --job-id daily-new-translation
bash bash -c echo daily_worker.py --job-id daily-inert
        """
        with patch.object(t, "command", return_value=processes):
            self.assertEqual(t.active_worker_job(), "daily-new-translation")

    def test_profile_cannot_be_inferred_from_ollama_ps(self):
        job = {"id": "daily-new-translation", "source_sha": "a"*64}
        self.assertIn("not recorded", t.profile_info(job, self.root))
        folder = self.root / "model-profiles"
        folder.mkdir()
        profile = folder / "daily-new-translation.json"
        profile.write_text(json.dumps({
            "job_id": job["id"],
            "source_sha": job["source_sha"],
            "model": "hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL",
        }))
        self.assertIn("PINNED TRANSLATOR", t.profile_info(job, self.root))
        self.assertIn("mismatched", t.profile_info(
            dict(job, source_sha="b"*64), self.root))

    def test_queue_summary_reads_only(self):
        text = t.queue_summary(self.db)
        self.assertIn("translating: 1", text)
        self.assertIn("queued: 1", text)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM cues").fetchone()[0], 5)


if __name__ == "__main__":
    unittest.main()
