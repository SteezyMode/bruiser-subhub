"""Offline regression for one actual American Dad PLaMo8B episode.
No model downloads, Docker, provider requests, Jellyfin changes, or real media.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import sys
import unittest
from unittest import mock

from tools import plamo3_watch_american_dad as app
from tools import plamo3_small_ab as small


class AmericanDadRealUseTests(unittest.TestCase):
    def test_creator_format_model_and_season_preference(self):
        app.self_test()
        self.assertEqual(app.GPU_LAYERS, 28)
        self.assertEqual(app.MODEL_HASH, "6b429549113ce0a61281ac72be195697241f89266f4247efec4893e4f580cf10")
        self.assertEqual(app.real.HISTORY, 2)
        self.assertEqual(app.real.STOP, ["<|plamo:tag|>", "<|plamo:bos|>"])
        self.assertLess(app.episode_priority("S08E09", False),
                        app.episode_priority("S19E10", False))
        self.assertLess(app.episode_priority("S19E10", False),
                        app.episode_priority("S19E07", True))
        self.assertEqual(app.episode_id(Path("/shows/American.Dad!.S08E10.mkv")),
                         "S08E10")
        self.assertIsNone(app.episode_id(Path("/shows/Other.Show.S08E10.mkv")))

    def test_draft_skips_sound_only_and_preserves_timestamps(self):
        cues = small.samples()[:3]
        completed = [
            dict(cues[0], japanese="<font size='36'>こんにちは。</font>",
                 status=app.SPOKEN),
            dict(cues[1], english="<font>[SIGHS]</font>",
                 japanese="<font>[SIGHS]</font>", status=app.SOLO_SDH),
            dict(cues[2], japanese="大丈夫", status=app.SPOKEN),
        ]
        srt, n = app.jellyfin_srt(completed)
        self.assertEqual(n, 2)
        self.assertNotIn("[SIGHS]", srt)
        reread = small.parse_srt(srt)
        self.assertEqual([r["start"] for r in reread],
                         [cues[0]["start"], cues[2]["start"]])
        self.assertIn("こんにちは。", srt)

    def test_held_cue_uses_actual_english_only_in_explicit_batch_mode(self):
        sample=small.samples()[:3]
        cues=[
            dict(sample[0],japanese="日本語",status=app.SPOKEN),
            dict(sample[1],english="What did you say?",
                 japanese="What did you say?",status=app.HELD),
            dict(sample[2],japanese="そうです。",status=app.SPOKEN)
        ]
        with self.assertRaisesRegex(RuntimeError,"unapproved_held"):
            app.jellyfin_srt(cues)
        srt,count=app.jellyfin_srt(cues,allow_held=True)
        self.assertEqual(count,2)
        self.assertIn("What did you say?",srt)
        self.assertIn("日本語",srt)
        self.assertEqual(len(small.parse_srt(srt)),3)

    def test_held_checkpoint_preserves_original_english_and_resume_position(self):
        with tempfile.TemporaryDirectory() as d:
            rows=small.samples()[:3]
            with mock.patch.object(app,"CHECKPOINT",Path(d)/"progress.sqlite3"):
                with app.checkpoints() as db:
                    src=rows[0]
                    db.execute("INSERT INTO translation VALUES (?,?,?,?,?,?,?,?)",
                               (0,src["number"],src["start"],src["end"],
                                src["english"],src["english"],app.HELD,.7))
                    db.commit()
                    cached=app.verify_checkpoints(db,rows)
                    self.assertEqual(len(cached),1)
                    self.assertEqual(cached[0]["status"],app.HELD)
                    self.assertEqual(app.previous_pairs(cached),[])
                    db.execute("UPDATE translation SET japanese='fabricated' WHERE idx=0")
                    db.commit()
                    with self.assertRaisesRegex(RuntimeError,"invalid_held"):
                        app.verify_checkpoints(db,rows)

    def test_held_limit_is_small(self):
        self.assertEqual(app.max_held_cues(400),8)
        self.assertEqual(app.max_held_cues(150),3)
        self.assertEqual(app.max_held_cues(1200),8)

    def test_sqlite_resume_rejects_source_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(app, "CHECKPOINT", Path(d)/"progress.sqlite3"):
                db = app.checkpoints()
                try:
                    rows = small.samples()[:2]
                    src = rows[0]
                    db.execute(
                        "INSERT INTO translation VALUES (?,?,?,?,?,?,?,?)",
                        (0, src["number"], src["start"], src["end"],
                         src["english"], "日本語", app.SPOKEN, .3))
                    db.commit()
                    valid = app.verify_checkpoints(db, rows)
                    self.assertEqual(len(valid), 1)
                    self.assertEqual(app.previous_pairs(valid),
                                     [(src["english"], "日本語")])
                    rows[0]["english"] = "SOURCE CHANGED"
                    with self.assertRaisesRegex(RuntimeError, "checkpoint_source_mismatch"):
                        app.verify_checkpoints(db, rows)
                finally:
                    db.close()

    def test_new_sidecar_create_only_video_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            video = Path(d) / "American.Dad.S19E07.mkv"
            video.write_bytes(b"real-media-is-not-changed")
            st = video.stat()
            selected = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
            intake = types.SimpleNamespace(
                probe=lambda _: {"audio_en": True, "embedded_en": 1},
                english_srt=lambda _: None,
            )
            dest = app.write_new_sidecar(
                video, selected, intake, "1\n00:00:00,000 --> 00:00:03,000\n日本語\n")
            self.assertEqual(dest.name, "American.Dad.S19E07.ja.PLaMo8B.srt")
            self.assertIn("日本語", dest.read_text())
            self.assertEqual(video.read_bytes(), b"real-media-is-not-changed")
            with self.assertRaisesRegex(RuntimeError, "no_replace"):
                app.write_new_sidecar(video, selected, intake, "TEST")
            self.assertIn("日本語", dest.read_text())

    def test_episode_discovery_prefers_fresh_s08(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            old = base / "American.Dad.S19E07.mkv"
            preferred = base / "American.Dad.S08E04.mkv"
            old.write_bytes(b"model fixture one")
            preferred.write_bytes(b"model fixture two")
            source = small.format_srt(
                [dict(number=i+1, start=small.timestamp(i*5),
                      end=small.timestamp(i*5+4), english="Hello.")
                 for i in range(200)], "english").encode()
            daily = types.SimpleNamespace(
                service=types.SimpleNamespace(SOURCE_ROOTS=(base,)),
                ensure_roots=lambda x:x,
                video_files=lambda roots: iter([old, preferred]),
                already_ja=lambda v: v == old,
                probe=lambda v: {"audio_en": True, "embedded_en": 0, "ja": False},
                english_srt=lambda v: None,
                source=lambda v,info: (source, 200, "embedded_english_text"),
            )
            fake = types.ModuleType("ja_first_stage_timing_audit")
            fake.safe_media_path = lambda v:Path(v)
            with mock.patch.dict(sys.modules, {"ja_first_stage_timing_audit": fake}):
                video, tag, cues, origin, mode, _ = app.find_episode(daily)
            self.assertEqual(video, preferred)
            self.assertEqual(tag, "S08E04")
            self.assertEqual(mode, "new")
            self.assertEqual(len(cues), 200)

    def test_missing_source_reports_failure_instead_of_fabrication(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            video=base/"American.Dad.S08E01.mkv"
            video.write_bytes(b"sample")
            daily=types.SimpleNamespace(
                service=types.SimpleNamespace(SOURCE_ROOTS=(base,)),
                ensure_roots=lambda x:x,
                video_files=lambda roots:iter([video]),
                already_ja=lambda _:False,
                probe=lambda _:{"audio_en":True,"embedded_en":None,"ja":False},
                english_srt=lambda _:None,
            )
            fake = types.ModuleType("ja_first_stage_timing_audit")
            fake.safe_media_path = lambda v:Path(v)
            with mock.patch.dict(sys.modules, {"ja_first_stage_timing_audit": fake}):
                with self.assertRaisesRegex(RuntimeError,"no_verified_english_source"):
                    app.find_episode(daily)


if __name__ == "__main__":
    unittest.main()
