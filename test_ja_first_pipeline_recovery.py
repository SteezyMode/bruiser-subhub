"""Integration regressions for source-first candidate progression (no host work)."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools import ja_first_candidate_progress as progress
from tools import ja_first_priority as priority
from tools import ja_first_stage_saved_batch as stage
from tools import ja_first_publish_queue as pub
from tools import ja_first_source_tracker as monitor
from tools import subhub_plamo_handoff as ai


class PipelineRecoveryTests(unittest.TestCase):
    ID="a"*32
    def row(self,path):
        return {"jellyfin_id":self.ID,"kind":"Movie","title":"Example Film",
                "year":2024,"status":"ready_ja_search","host_path":str(path),
                "genres":["Horror"]}

    def test_wait_for_existing_stage_decision_before_another_download(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            video=folder/"Example Film (2024).mkv"
            video.write_bytes(b"movie placeholder")
            db=folder/"stage.sqlite3"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE staged("
                    "jellyfin_id TEXT, subtitle_id TEXT,sha256 TEXT,status TEXT)")
                connection.execute("INSERT INTO staged VALUES(?,?,?,?)",
                    (self.ID,"1000","a"*64,"staged"))
            db.chmod(0o600)
            with patch.object(stage,"STAGE_DB",db), \
                 patch.object(stage.candidate_progress,"known",return_value=None):
                self.assertFalse(stage.alternate_ready(self.row(video)))
            with patch.object(stage,"STAGE_DB",db), \
                 patch.object(stage.candidate_progress,"known",return_value="held"):
                self.assertTrue(stage.alternate_ready(self.row(video)))
            with sqlite3.connect(db) as connection:
                connection.execute("UPDATE staged SET status='held_duration_mismatch'")
            with patch.object(stage,"STAGE_DB",db):
                self.assertTrue(stage.alternate_ready(self.row(video)))

    def test_stage_next_saved_release_is_ranked_not_redownloaded(self):
        row=self.row("/mnt/2TB/Plex Expansion/Movies/Horror/Example Film 2024 1080p BluRay.mkv")
        history=[(self.ID,json.dumps({"candidates":[
            {"subtitle_id":"1000","provider":"opensubtitles","score":95,
             "grade":"plausible","filename":"Example.Film.2024.WEBRip.720p.ja.srt"},
            {"subtitle_id":"2000","provider":"opensubtitles","score":60,
             "grade":"plausible","filename":"Example.Film.2024.BluRay.1080p.ja.srt"},
        ]}))]
        with patch.object(stage,"identity_ok",return_value=True), \
             patch.object(stage,"rejected_duration_candidates",return_value=set()), \
             patch.object(stage,"alternate_ready",return_value=True), \
             patch.object(stage.priorities,"active_coverage_queue",return_value=None):
            selected=stage.choices({self.ID:row},history,set(),1,"movie")
            self.assertEqual(selected[0]["candidate"]["subtitle_id"],"2000")
            selected2=stage.choices({self.ID:row},history,{(self.ID,"2000")},1,"movie")
            self.assertEqual(selected2[0]["candidate"]["subtitle_id"],"1000")

    def test_review_grade_never_beats_plausible_on_filename(self):
        row=self.row("/mnt/2TB/Plex Expansion/Movies/Horror/Example Film 2024 BluRay.mkv")
        history=[(self.ID,json.dumps({"candidates":[
            {"subtitle_id":"1000","provider":"opensubtitles","score":95,
             "grade":"review","filename":"Example.Film.2024.BluRay.ja.srt"},
            {"subtitle_id":"2000","provider":"opensubtitles","score":50,
             "grade":"plausible","filename":"Example.Film.2024.ja.srt"},
        ]}))]
        with patch.object(stage,"identity_ok",return_value=True), \
             patch.object(stage,"rejected_duration_candidates",return_value=set()), \
             patch.object(stage,"alternate_ready",return_value=True), \
             patch.object(stage.priorities,"active_coverage_queue",return_value=None):
            self.assertEqual(stage.choices({self.ID:row},history,set(),1,"movie")[0]
                             ["candidate"]["subtitle_id"],"2000")

    def test_deterministic_full_failure_records_attempts_not_publication(self):
        row=self.row("/mnt/2TB/Plex Expansion/Movies/Horror/Example Film 2024.mkv")
        with patch.object(pub,"existing_verdict",return_value=("absent",row)), \
             patch.object(pub.progress,"fingerprint",return_value="f"*64), \
             patch.object(pub.progress,"known",return_value=None), \
             patch.object(pub.progress,"remember",return_value=True) as receipts, \
             patch.object(pub.alass,"available",return_value=True), \
             patch.object(pub.alass,"prepare",side_effect=RuntimeError("alass_reordered_cues")), \
             patch.object(pub.ff,"prepare",side_effect=RuntimeError("sync_cue_count_changed")), \
             patch.object(pub,"direct_candidate",return_value=None), \
             patch.object(pub.shifted,"preparation",
                          side_effect=RuntimeError("no_candidate_passed_trusted_sync_correction")):
            with self.assertRaisesRegex(RuntimeError,
                                         "no_candidate_passed_trusted_sync_correction"):
                pub.choose(self.ID,[("1000","a"*64)],record_failures=True)
        self.assertEqual([x.args[2] for x in receipts.call_args_list],
                         ["alass","ffsubsync","final"])

    def test_source_journal_reports_next_action_without_model_running(self):
        events=[
            (100,"RUNNING_SOURCES_ONLY_CYCLE search_budget=600 stage_budget=200 publish_limit=200"),
            (101,"SOURCE SCOPE: movies-no-anime"),
            (102,"=== PUBLISH VERIFIED JA ==="),
            (103,"MEDIA: "+"a"*32+" | candidate IDs: 1000"),
            (104,"RESULT: Example Film | held_unchanged"),
            (105,"NEXT_ACTION: "+json.dumps(
                {"jellyfin_id":"a"*32,
                 "action":"stage_alternate_saved_japanese"})),
            (106,"NEXT_ACTION: "+json.dumps(
                {"jellyfin_id":"b"*32,
                 "action":"offer_owner_reviewed_plamo_after_english_validation"})),
        ]
        report=monitor.parse(events)
        self.assertEqual(report["skipped_unchanged"],1)
        self.assertEqual(report["next_actions"]["stage_alternate_saved_japanese"],1)
        self.assertEqual(
            report["next_actions"]["offer_owner_reviewed_plamo_after_english_validation"],1)

    def test_owner_review_movie_uses_same_exact_identity_and_source_gate(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"ja.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE searches("
                           "jellyfin_id TEXT PRIMARY KEY,outcome TEXT,searched_at INTEGER)")
                db.execute("INSERT INTO searches VALUES(?,?,?)",
                           (self.ID,"plausible",int(time.time())))
            path.chmod(0o600)
            movie={"jellyfin_id":self.ID,"kind":"Movie",
                   "title":"Example Film","target":"ja","state":"held",
                   "english_text":0,"action":"align_existing_staged_ja",
                   "path":"/media/movie.mkv"}
            with patch.object(ai,"SEARCH_DB",path):
                ai.validate_row(movie,owner_review=True)
                with self.assertRaisesRegex(RuntimeError,"japanese_sourcing_not_exhausted"):
                    ai.validate_row(movie,owner_review=False)
                with sqlite3.connect(path) as db:
                    db.execute("UPDATE searches SET outcome='partial'")
                with self.assertRaisesRegex(RuntimeError,"review_source_evidence"):
                    ai.validate_row(movie,owner_review=True)


if __name__=="__main__":
    unittest.main()
