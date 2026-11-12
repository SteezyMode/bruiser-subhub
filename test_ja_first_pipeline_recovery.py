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

    def test_malformed_remote_download_is_cached_but_quota_failure_is_not(self):
        row=self.row("/mnt/2TB/Plex Expansion/Movies/Horror/Example Film 2024.mkv")
        candidate={"provider":"opensubtitles","subtitle_id":"1000",
                   "filename":"Example.Film.2024.ja.srt","release_info":"Example 2024"}
        job={"row":row,"candidate":candidate}
        import subprocess
        def fake_run(command,**kwargs):
            body={"result":"blocked","error_type":"RuntimeError",
                  "error":"too_few_japanese_characters"}
            stdout=("SUBHUB_DOWNLOAD_REQUEST: opensubtitles\n"
                    "SUBHUB_DOWNLOAD_RECEIVED: 1234\n"
                    "STAGE_RESULT_JSON:"+json.dumps(body)+"\n")
            return subprocess.CompletedProcess(command,1,stdout,"")
        with patch.object(stage,"duration_if_safe",return_value=1200), \
             patch.object(stage.subprocess,"run",side_effect=fake_run), \
             patch.object(stage,"record_native_download_attempt"), \
             patch.object(stage.candidate_progress,"fingerprint",return_value="f"*64), \
             patch.object(stage.candidate_progress,"remember",return_value=True) as mark:
            with self.assertRaisesRegex(RuntimeError,"container_staging_blocked"):
                stage.run_one(job,None)
            mark.assert_called_once()
            self.assertIn("too_few_japanese_characters",str(mark.call_args))
        def quota_run(command,**kwargs):
            body={"result":"blocked","error_type":"RuntimeError",
                  "error":"opensubtitles_pool_disabled_cooling_or_exhausted"}
            stdout=("SUBHUB_DOWNLOAD_REQUEST: opensubtitles\n"
                    "STAGE_RESULT_JSON:"+json.dumps(body)+"\n")
            return subprocess.CompletedProcess(command,1,stdout,"")
        with patch.object(stage,"duration_if_safe",return_value=1200), \
             patch.object(stage.subprocess,"run",side_effect=quota_run), \
             patch.object(stage,"record_native_download_attempt"), \
             patch.object(stage.candidate_progress,"remember") as mark:
            with self.assertRaisesRegex(RuntimeError,"container_staging_blocked"):
                stage.run_one(job,None)
            mark.assert_not_called()

    def test_cached_malformed_candidate_is_skipped_and_alternate_remains(self):
        with tempfile.TemporaryDirectory() as temp:
            video=Path(temp)/"Example Film 2024.mkv"
            video.write_bytes(b"video")
            row=self.row(video)
            history=[(self.ID,json.dumps({"candidates":[
                {"subtitle_id":"1000","provider":"opensubtitles","score":99,
                 "grade":"plausible","language":"ja",
                 "filename":"Example.Film.2024.ja.srt"},
                {"subtitle_id":"2000","provider":"opensubtitles","score":70,
                 "grade":"plausible","language":"ja",
                 "filename":"Example.Film.2024.ja.srt"},
            ]}))]
            def known(jid,sid,engine,key,**kwargs):
                return "too_few_japanese_characters" if sid=="1000" else None
            with patch.object(stage,"identity_ok",return_value=True), \
                 patch.object(stage,"rejected_duration_candidates",return_value=set()), \
                 patch.object(stage,"alternate_ready",return_value=True), \
                 patch.object(stage.priorities,"active_coverage_queue",return_value=None), \
                 patch.object(stage.candidate_progress,"known",side_effect=known):
                selected=stage.choices({self.ID:row},history,set(),1,"movie")
            self.assertEqual(selected[0]["candidate"]["subtitle_id"],"2000")

    def test_trusted_direct_fit_agrees_with_timing_auditor(self):
        from tools import ja_first_publish_staged as gate
        strong={"status":"fit","reference_trust":"trusted_embedded",
                "matching_start_fraction":0.954,"best_offset_seconds":0.3}
        self.assertTrue(gate.trusted_direct_fit(strong))
        self.assertFalse(gate.trusted_direct_fit(dict(strong,best_offset_seconds=0.8)))
        self.assertFalse(gate.trusted_direct_fit(dict(strong,reference_trust="untrusted_sidecar")))
        self.assertFalse(gate.trusted_direct_fit(dict(strong,matching_start_fraction=0.50)))
        self.assertFalse(gate.trusted_direct_fit(dict(strong,status="uncertain")))

    def test_large_constant_shift_requires_near_perfect_independent_match(self):
        from tools import ja_first_publish_shifted as shifted
        found={"status":"shift_needed","reference_trust":"trusted_embedded",
               "matching_start_fraction":0.989,"best_offset_seconds":26.1}
        self.assertTrue(shifted.eligible_constant_shift(found))
        self.assertFalse(shifted.eligible_constant_shift(dict(
            found,matching_start_fraction=0.955)))
        self.assertFalse(shifted.eligible_constant_shift(dict(
            found,reference_trust="untrusted_sidecar")))
        self.assertFalse(shifted.eligible_constant_shift(dict(
            found,best_offset_seconds=32.0)))
        self.assertTrue(shifted.eligible_constant_shift(dict(
            found,matching_start_fraction=0.955,best_offset_seconds=1.1)))

    def test_shift_26_seconds_preserves_every_subtitle_dialogue_and_timing(self):
        from tools import ja_first_publish_shifted as shifted
        from tools import ja_first_publish_staged as gate
        def clock(ms):
            hh,x=divmod(ms,3600000)
            mm,x=divmod(x,60000)
            ss,m=divmod(x,1000)
            return f"{hh:02d}:{mm:02d}:{ss:02d},{m:03d}"
        raw=("\n\n".join(
            f"{i+1}\n{clock(31000+i*3700)} --> {clock(32000+i*3700)}"
            "\n日本語のセリフ"
            for i in range(140))+"\n").encode("utf-8")
        corrected,num=shifted.shift_srt(raw,26.1,runtime=1200)
        self.assertEqual(num,140)
        self.assertEqual(gate.validate_srt(raw,1200),
                         gate.validate_srt(corrected,1200))
        self.assertIn(b"00:00:04,900",corrected)
        self.assertNotIn(b"00:00:31,000",corrected)
        self.assertEqual(corrected.count("日本語のセリフ".encode()),140)
        with self.assertRaisesRegex(RuntimeError,"shifted_subtitle_exceeds_video_duration"):
            shifted.shift_srt(raw,26.1,runtime=300)
        with self.assertRaisesRegex(RuntimeError,"shift_outside_conservative_policy"):
            shifted.shift_srt(raw,31.5)
        early=raw.replace(b"00:00:31,000",b"00:00:02,000",1)
        with self.assertRaisesRegex(RuntimeError,"shift_would_invalidate_cue"):
            shifted.shift_srt(early,26.1)

    def test_stage_failure_receipt_expires_but_alignment_receipts_remain(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/"candidate.sqlite3"
            key="a"*64
            progress.remember(self.ID,"1000","stage",key,
                              RuntimeError("too_few_japanese_characters"),db_path=db)
            self.assertEqual(progress.known(
                self.ID,"1000","stage",key,db_path=db,max_age_seconds=86400),
                "too_few_japanese_characters")
            with sqlite3.connect(db) as cx:
                cx.execute("UPDATE failures SET recorded_at=recorded_at-86401")
            self.assertIsNone(progress.known(
                self.ID,"1000","stage",key,db_path=db,max_age_seconds=86400))
            self.assertIsNotNone(progress.known(
                self.ID,"1000","stage",key,db_path=db))
            self.assertFalse(progress.deterministic_stage_rejection(
                "opensubtitles_pool_disabled_cooling_or_exhausted"))
            self.assertTrue(progress.deterministic_stage_rejection(
                "unrecognized_subtitle_timing_or_encoding"))

    def test_exact_title_no_year_is_eligible_but_other_films_rejected(self):
        movie={"kind":"Movie","title":"The Substance","year":2024}
        candidate={"provider":"opensubtitles","subtitle_id":"1234567",
                   "language":"ja","filename":"The.Substance.BluRay.ja.srt",
                   "release_info":"The Substance BluRay","grade":"review"}
        self.assertTrue(stage.identity_ok(movie,candidate))
        self.assertFalse(stage.identity_ok(movie,dict(
            candidate,filename="The.Substance.2010.BluRay.ja.srt",
            release_info="The Substance 2010 BluRay")))
        self.assertFalse(stage.identity_ok(movie,dict(
            candidate,filename="The.Substance.of.Other.Movies.ja.srt",
            release_info="Other Movie")))

    def test_new_japanese_sidecar_excludes_stale_library_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            video=root/"Example Film 2024.mkv"
            video.write_bytes(b"movie")
            (root/"Example Film 2024.ja.srt").write_text("already covered")
            row=self.row(video)
            history=[(self.ID,json.dumps({"candidates":[{
                "subtitle_id":"1000","provider":"opensubtitles","score":90,
                "grade":"plausible","language":"ja",
                "filename":"Example.Film.2024.ja.srt"}]}))]
            with patch.object(stage,"identity_ok",return_value=True), \
                 patch.object(stage,"rejected_duration_candidates",return_value=set()), \
                 patch.object(stage,"alternate_ready",return_value=True), \
                 patch.object(stage.priorities,"active_coverage_queue",return_value=None):
                selected=stage.choices({self.ID:row},history,set(),1,"movie")
            self.assertEqual(selected,[])

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

    def _run_failed_alignment(self, candidates, alass_error, ff_error):
        """Simulate mutable failure receipts without accessing actual media."""
        row=self.row("/mnt/2TB/Plex Expansion/Movies/Horror/Example Film 2024.mkv")
        saved={}
        def known(jid,sid,engine,key):
            return saved.get((str(sid),engine))
        def remember(jid,sid,engine,key,exc):
            if progress.stable_failure(exc):
                saved[(str(sid),engine)]=str(exc)
                return True
            return False
        aligned=[]
        def do_alass(jid,sid):
            aligned.append(sid)
            if isinstance(alass_error,BaseException):
                raise alass_error
            return alass_error(jid,sid)
        with patch.object(pub,"existing_verdict",return_value=("absent",row)), \
             patch.object(pub.progress,"fingerprint",return_value="f"*64), \
             patch.object(pub.progress,"known",side_effect=known), \
             patch.object(pub.progress,"remember",side_effect=remember), \
             patch.object(pub.alass,"available",return_value=True), \
             patch.object(pub.alass,"prepare",side_effect=do_alass), \
             patch.object(pub.ff,"prepare",side_effect=ff_error), \
             patch.object(pub,"direct_candidate",return_value=None), \
             patch.object(pub.shifted,"preparation",
                          side_effect=RuntimeError("no_candidate_passed_trusted_sync_correction")):
            with self.assertRaisesRegex(
                    RuntimeError,"no_candidate_passed_trusted_sync_correction"):
                pub.choose(self.ID,candidates,record_failures=True)
        return saved,aligned

    def test_deterministic_full_failure_records_attempts_not_publication(self):
        saved,_=self._run_failed_alignment(
            [("1000","a"*64)],RuntimeError("alass_reordered_cues"),
            RuntimeError("sync_cue_count_changed"))
        self.assertEqual(set(saved),
                         {("1000","alass"),("1000","ffsubsync"),("final","final")})

    def test_fourth_staged_candidate_must_not_be_marked_exhausted(self):
        candidates=[(str(1000+i),f"{i:064x}") for i in range(4)]
        saved,attempted=self._run_failed_alignment(
            candidates,RuntimeError("alass_reordered_cues"),
            RuntimeError("sync_cue_count_changed"))
        self.assertNotIn(("final","final"),saved)
        self.assertEqual(attempted,["1000","1001","1002"])
        self.assertNotIn(("1003","alass"),saved)

    def test_transient_alignment_failure_must_not_mark_title_exhausted(self):
        saved,_=self._run_failed_alignment(
            [("1000","a"*64)],RuntimeError("alass_failed_no_valid_output"),
            RuntimeError("sync_cue_count_changed"))
        self.assertNotIn(("final","final"),saved)
        self.assertNotIn(("1000","alass"),saved)
        self.assertIn(("1000","ffsubsync"),saved)

    def test_next_action_requires_proven_final_failure_before_plamo(self):
        with patch.object(pub.direct,"read_inventory",return_value={
                 "host_path":"/tmp/movie.mkv","kind":"Movie"}), \
             patch.object(pub.progress,"fingerprint",return_value="f"*64), \
             patch.object(pub.progress,"known",return_value=None), \
             patch.object(pub.progress,"next_action",
                          return_value="offer_owner_reviewed_plamo_after_english_validation"), \
             patch.object(pub.staging,"identity_ok",return_value=True), \
             patch("builtins.print") as output:
            pub.report_next_action(self.ID,[("1000","a"*64)])
        combined=" ".join(str(x) for x in output.call_args_list)
        self.assertIn("complete_or_retry_staged_validation",combined)
        self.assertNotIn("owner_approval_required': True",combined)


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
