"""Offline, no-GPU tests of the queue-owned PLaMo subtitle handoff."""
from pathlib import Path
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from tools import subhub_plamo_handoff as ai


class HandoffTests(unittest.TestCase):
    def db(self, folder):
        path = Path(folder) / "coverage.sqlite3"
        db=sqlite3.connect(path)
        db.executescript("""
            CREATE TABLE media (
                path TEXT PRIMARY KEY,jellyfin_id TEXT,
                kind TEXT,title TEXT,series TEXT,en_text INTEGER
            );
            CREATE TABLE tasks (
                path TEXT,target TEXT,action TEXT,state TEXT,
                priority INTEGER,active INTEGER
            );
        """)
        db.execute(
            "INSERT INTO media VALUES(?,?,?,?,?,?)",
            ("/media/A/movie.mkv","fid_A","Movie","Example film","",1))
        db.execute(
            "INSERT INTO media VALUES(?,?,?,?,?,?)",
            ("/media/B/episode.mkv","fid_B","Episode","The Episode","The Series",0))
        db.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?)",
            ("/media/A/movie.mkv","ja","validate_english_for_ja_fallback",
             "pending",51,1))
        db.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?)",
            ("/media/B/episode.mkv","ja","recover_english_for_ja_fallback",
             "pending",61,1))
        db.commit()
        db.close()
        path.chmod(0o600)
        return path

    def test_only_source_exhausted_targets_offered(self):
        with tempfile.TemporaryDirectory() as t:
            path=self.db(t)
            with ai.safe_db(path) as db:
                rows=ai.eligible(db)
                self.assertEqual(len(rows),2)
                self.assertEqual(rows[0]["jellyfin_id"],"fid_A")
                ai.validate_row(rows[0])
                with self.assertRaisesRegex(RuntimeError,"japanese_sourcing_not_exhausted"):
                    ai.validate_row(rows[1])
                self.assertEqual(ai.eligible(db,"fid_A")[0]["series"],"")

    def test_initial_search_candidate_must_not_translate(self):
        row={"jellyfin_id":"a","path":"/media/a.mkv",
             "target":"ja","kind":"Movie","state":"pending",
             "english_text":1,"action":"search_ja"}
        with self.assertRaisesRegex(RuntimeError,"japanese_sourcing_not_exhausted"):
            ai.validate_row(row)

    def test_english_indicated_not_equal_verified_ready(self):
        row={"jellyfin_id":"a","path":"/media/a.mkv",
             "target":"ja","kind":"Movie","state":"pending",
             "english_text":0,"action":"validate_english_for_ja_fallback"}
        with self.assertRaisesRegex(RuntimeError,"english_text_not_indicated"):
            ai.validate_row(row)

    def test_public_queue_db_refused(self):
        with tempfile.TemporaryDirectory() as t:
            path=self.db(t)
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError,"private_coverage_queue"):
                ai.safe_db(path)

    def test_media_item_folders_distinct_and_stable(self):
        with tempfile.TemporaryDirectory() as t:
            p1=ai.private_folder("a","/media/1.mkv",t)
            p2=ai.private_folder("b","/media/1.mkv",t)
            self.assertNotEqual(p1,p2)
            self.assertEqual(p1,ai.private_folder("a","/media/1.mkv",t))
            self.assertTrue(p1.name.startswith("ja-"))

    def test_status_file_atomic_and_private(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"state.json"
            ai.atomic_json(path,{"result":"checkpointed"})
            self.assertEqual(json.loads(path.read_text())["result"],"checkpointed")
            self.assertEqual(path.stat().st_mode & 0o077,0)
            ai.atomic_json(path,{"result":"resumed"})
            self.assertEqual(json.loads(path.read_text())["result"],"resumed")

    def test_state_symlink_refused(self):
        with tempfile.TemporaryDirectory() as t:
            target=Path(t)/"target.json"
            target.write_text("{}")
            path=Path(t)/"state.json"
            path.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError,"unsafe_state_symlink"):
                ai.atomic_json(path,{})

    def test_existing_translator_pid_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"batch.pid"
            path.write_text(str(os.getpid()))
            path.chmod(0o600)
            self.assertTrue(ai.other_translation_running(path))
            path.write_text("999999999")
            self.assertFalse(ai.other_translation_running(path))

    def test_unsafe_translator_pid_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"batch.pid"
            path.write_text("not_a_pid")
            path.chmod(0o600)
            with self.assertRaisesRegex(RuntimeError,"invalid_previous_translation_pid_file"):
                ai.other_translation_running(path)

    def test_source_batch_blocks_gpu_even_before_hardware_use(self):
        row={"jellyfin_id":"x"}
        with patch.object(ai,"recent_running_source",return_value=True), \
             patch.object(ai,"modules",side_effect=AssertionError("no modules")):
            with self.assertRaisesRegex(RuntimeError,"source_batch_still_running"):
                ai.translate(row,Path("/tmp/nonexistent"),
                             (None,None,None,None,None,None,None))

    def test_missing_source_is_not_translated(self):
        class Daily:
            @staticmethod
            def already_ja(video): return False
            @staticmethod
            def english_srt(video): return None
        info={"audio_en":True,"ja":False,"embedded_en":None}
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/"movie.mkv"
            video.write_bytes(b"not-a-video (preflight fixture only)")
            with self.assertRaisesRegex(RuntimeError,"english_text_source_not_available"):
                ai.saved_media(video,"fid",info,Daily,
                               None,None,None,lambda p:Path(p))

    def test_source_routing_is_not_based_on_filename_only(self):
        self.assertNotIn("American Dad",ai.__doc__ or "")
        self.assertTrue(ai.ALLOWED_ACTIONS.issubset(ai.PLANNABLE_ACTIONS))


if __name__ == "__main__":
    unittest.main()
