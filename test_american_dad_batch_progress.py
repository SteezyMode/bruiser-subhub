"""Read-only American Dad live-progress tests, without host media/GPU."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from tools import american_dad_batch_progress as p


class BatchProgressTests(unittest.TestCase):
    def test_before_start_shows_not_started_not_fake_percentage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with mock.patch.multiple(p,STATE=root,PLAN=root/"queue.json",
                     STATUS=root/"run-status.jsonl",PIDFILE=root/"batch.pid",
                     LOG=root/"batch.log"):
                result=p.snapshot()
            self.assertEqual(result["status"],"NOT STARTED")
            self.assertEqual(result["total"],0)
            self.assertEqual(result["done"],0)

    def test_bars_exact_start_middle_finish(self):
        self.assertEqual(p.bar(0,20,10),"["+"░"*10+"]")
        self.assertEqual(p.bar(10,20,10),"["+"█"*5+"░"*5+"]")
        self.assertEqual(p.bar(20,20,10),"["+"█"*10+"]")

    def test_real_tracks_define_completed_total_and_sqlite_cue_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            video1=root/"American.Dad.S20E01.mkv"
            video2=root/"American.Dad.S20E02.mkv"
            for video in (video1,video2):
                video.write_bytes(b"fixture")
            sidecar=video1.with_name(video1.stem+".ja.PLaMo8B.srt")
            sidecar.write_text("Japanese")
            queue=[
                {"episode":"S20E01","video":str(video1),"cue_source":"embedded"},
                {"episode":"S20E02","video":str(video2),"cue_source":"embedded"},
            ]
            (root/"queue.json").write_text(json.dumps({
                "version":1,"library":str(root),"episodes":queue,
                "initial_existing_ja":4,"initial_missing_english":300}))
            (root/"batch.log").write_text(
                "=== EPISODE 1/2: S20E01 ===\n"
                "=== EPISODE 2/2: S20E02 ===\n")
            (root/"run-status.jsonl").write_text(
                '{"episode":"S20E01","status":"published"}\n')
            second=p.episode_dir(queue[1])
            # Patch STATE before computing folder identity, as in production.
            with mock.patch.multiple(p,STATE=root,PLAN=root/"queue.json",
                     STATUS=root/"run-status.jsonl",PIDFILE=root/"batch.pid",
                     LOG=root/"batch.log"),\
                 mock.patch.object(p,"live_pid",return_value=999):
                second=p.episode_dir(queue[1])
                second.mkdir()
                (second/"episode.json").write_text(json.dumps(
                    {"episode":"S20E02","video":str(video2),"cue_count":400}))
                db=sqlite3.connect(second/"progress.sqlite3")
                db.execute("CREATE TABLE translation(idx INTEGER PRIMARY KEY)")
                db.executemany("INSERT INTO translation VALUES (?)",
                               [(i,) for i in range(130)])
                db.commit()
                db.close()
                result=p.snapshot()
            self.assertEqual(result["total"],2)
            self.assertEqual(result["done"],1)
            self.assertEqual(result["current"],"S20E02")
            self.assertEqual((result["cues_done"],result["cues_total"]),
                             (130,400))
            self.assertEqual(result["status"],"RUNNING")

    def test_completed_file_not_completed_event_drives_success(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); video=root/"American.Dad.S20E01.mkv"
            video.write_bytes(b"movie")
            (root/"queue.json").write_text(json.dumps({
                "version":1,"library":str(root),
                "episodes":[{"episode":"S20E01","video":str(video)}]}))
            (root/"run-status.jsonl").write_text(
                '{"episode":"S20E01","status":"published"}\n')
            with mock.patch.multiple(p,STATE=root,PLAN=root/"queue.json",
                     STATUS=root/"run-status.jsonl",PIDFILE=root/"batch.pid",
                     LOG=root/"batch.log"),\
                 mock.patch.object(p,"live_pid",return_value=None):
                result=p.snapshot()
            self.assertEqual(result["done"],0)
            self.assertEqual(result["status"],"STOPPED / PAUSED")

    def test_watch_is_read_only_no_database_creation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); row={"episode":"S21E07",
                "video":str(root/"American.Dad.S21E07.mkv")}
            with mock.patch.object(p,"STATE",root):
                self.assertEqual(p.cue_progress(row),(0,0))
                self.assertFalse(p.episode_dir(row).exists())


if __name__=="__main__":
    unittest.main()
