"""Offline regression for create-only promotion of cached movie reviews."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
from tools import subhub_review_promote as promote


def film(jid="a"*32):
    return {"jellyfin_id":jid,"kind":"Movie","title":"A Film",
            "year":2020,"status":"ready_ja_search",
            "host_path":"/mnt/2TB/Plex Expansion/Movies/Drama/A Film.mkv"}


def saved(sid="123456"):
    return {"provider":"opensubtitles","subtitle_id":sid,
            "language":"ja","grade":"review","filename":"A.Film.2020.ja.srt",
            "release_info":"A.Film.2020"}


def receipt(status="timing_trial_pass_identity_eligible", verified=True):
    return {"status":status,"metadata_identity_verified":verified}


class ReviewPromotionTests(unittest.TestCase):
    def test_identity_unverified_cannot_enter_promotion_queue(self):
        row=film()
        c=saved()
        with patch.object(promote.review,"private_bytes_present",return_value=True):
            jobs,counts,_=promote.select(
                [row],source_reader=lambda _: ([(row,c)],{"candidate_jobs":1}),
                receipt_reader=lambda *_:receipt(verified=False),
                identity_check=lambda *_:False)
        self.assertEqual(jobs,[])
        self.assertEqual(counts["unverified_movie_identity"],1)

    def test_even_new_identity_predicate_does_not_overrule_failed_saved_trial(self):
        row=film()
        c=saved()
        with patch.object(promote.review,"private_bytes_present",return_value=True):
            jobs,counts,_=promote.select(
                [row],source_reader=lambda _: ([(row,c)],{"candidate_jobs":1}),
                receipt_reader=lambda *_:receipt(verified=False),
                identity_check=lambda *_:True)
        self.assertEqual(jobs,[])
        self.assertEqual(counts["metadata_verdict_changed_recheck"],1)

    def test_selects_only_one_verified_source_per_movie_and_prefers_pass(self):
        row=film()
        c1=saved("123456")
        c2=saved("234567")
        other=film("b"*32)
        c3=saved("345678")
        def saved_receipt(row,c):
            return receipt("timing_trial_held" if c is c1
                           else "timing_trial_pass_identity_eligible")
        with patch.object(promote.review,"private_bytes_present",return_value=True):
            jobs,counts,_=promote.select(
                [row,other],
                source_reader=lambda _:(
                    [(row,c1),(row,c2),(other,c3)],{"candidate_jobs":3}),
                receipt_reader=saved_receipt,
                identity_check=lambda *_:True)
        self.assertEqual(len(jobs),2)
        self.assertEqual(jobs[0][1]["subtitle_id"],"234567")
        self.assertEqual(counts["alternate_cached_deferred"],1)
        self.assertEqual(counts["distinct_movies_eligible"],2)

    def test_reference_audit_reads_only_cached_and_same_video_references(self):
        row=film()
        c=saved()
        raw=b"original"
        with patch.object(promote.stage,"duration_if_safe",return_value=600), \
             patch.object(promote,"cached_source",return_value=(raw,{})), \
             patch.object(promote.ff,"parse_cues",return_value=[
                 {"end":1000},{"end":470000}]), \
             patch.object(promote.gate,"safe_media_path",
                          return_value=Path(row["host_path"])), \
             patch.object(promote.alass,"_embedded_english",return_value=None), \
             patch.object(promote.alass,"_intensive_external_english",
                          return_value=None), \
             patch.object(promote.alass,"_intensive_jellyfin_english",
                          return_value=b"English SRT"), \
             patch.object(promote.alass,"intensive_align") as intensive, \
             patch.object(promote.stage,"stage_db") as db, \
             patch.object(promote.gate,"publish") as publish:
            report=promote.audit_references(row,c)
        self.assertEqual(report["original_subtitle_ends_pct"],78.3)
        self.assertTrue(report["cross_reference_available"])
        self.assertTrue(report["english_jellyfin_indexed"])
        self.assertFalse(report["english_embedded"])
        intensive.assert_not_called()
        db.assert_not_called()
        publish.assert_not_called()

    def test_reference_audit_reports_no_english_without_deeming_ja_bad(self):
        row=film()
        with patch.object(promote.stage,"duration_if_safe",return_value=600), \
             patch.object(promote,"cached_source",return_value=(b"source",{})), \
             patch.object(promote.ff,"parse_cues",return_value=[
                 {"end":1000},{"end":570000}]), \
             patch.object(promote.gate,"safe_media_path",
                          return_value=Path(row["host_path"])), \
             patch.object(promote.alass,"_embedded_english",return_value=None), \
             patch.object(promote.alass,"_intensive_external_english",
                          return_value=None), \
             patch.object(promote.alass,"_intensive_jellyfin_english",
                          return_value=None):
            report=promote.audit_references(row,saved())
        self.assertEqual(report["original_subtitle_ends_pct"],95.0)
        self.assertFalse(report["cross_reference_available"])

    def test_cross_reference_requires_independent_english_and_audio(self):
        row=film()
        with patch.object(promote.gate,"safe_media_path",
                          return_value=Path(row["host_path"])), \
             patch.object(promote.gate,"subprocess_duration",return_value=5400), \
             patch.object(promote.gate,"ffprobe_streams",return_value=([],None)), \
             patch.object(promote.gate,"check_no_existing_ja"), \
             patch.object(promote.ff,"keep_source_dialogue",return_value=b"aligned"), \
             patch.object(promote.alass,"assess",return_value={}), \
             patch.object(promote.alass,"intensive_align",return_value=(
               b"aligned",{"alignment_reference":"video_audio",
                           "intensive_cross_reference":None,
                           "intensive_agreement_thirds":[]})):
            with self.assertRaisesRegex(RuntimeError,
                                        "no_independent_audio_english_agreement"):
                promote.cross_check(row,saved(),b"source",5400)

    def test_missing_english_uses_two_audio_engines_with_unchanged_guards(self):
        video=Path(film()["host_path"])
        source=b"source Japanese"
        aligned=b"aligned Japanese"
        subaligned=b"ffsubsync Japanese"
        with patch.object(promote.gate,"validate_srt",return_value={"cues":100}), \
             patch.object(promote.ff,"keep_source_dialogue",
                          side_effect=lambda _, candidate:candidate), \
             patch.object(promote.alass,"align",
                          return_value=(aligned,"video_audio")) as ala, \
             patch.object(promote.alass,"assess",return_value={}), \
             patch.object(promote.ff,"align_in_container",
                          return_value=subaligned) as ff_engine, \
             patch.object(promote.ff,"repair_minor_overlaps",
                          return_value=(subaligned,{})), \
             patch.object(promote.ff,"check_alignment",
                          return_value={"mode":"corrected"}) as guard, \
             patch.object(promote.alass,"_intensive_agreement",
                          return_value=[0.96,0.94,0.98]) as agree:
            output,evidence=promote.audio_consensus(video,source,5400)
        self.assertEqual(output,aligned)
        self.assertEqual(evidence["audio_engine_consensus"],
                         "ffsubsync_video_audio")
        self.assertEqual(evidence["audio_consensus_thirds"],
                         [0.96,0.94,0.98])
        ala.assert_called_once()
        ff_engine.assert_called_once_with(video,source)
        guard.assert_called_once_with(source,subaligned,5400)
        agree.assert_called_once_with(aligned,subaligned)

    def test_audio_consensus_rejects_disagreement(self):
        with patch.object(promote.gate,"validate_srt",return_value={}), \
             patch.object(promote.ff,"keep_source_dialogue",
                          side_effect=lambda _,candidate:candidate), \
             patch.object(promote.alass,"align",
                          return_value=(b"ALASS","video_audio")), \
             patch.object(promote.alass,"assess",return_value={}), \
             patch.object(promote.ff,"align_in_container",
                          return_value=b"FFSUBSYNC"), \
             patch.object(promote.ff,"repair_minor_overlaps",
                          return_value=(b"FFSUBSYNC",{})), \
             patch.object(promote.ff,"check_alignment"), \
             patch.object(promote.alass,"_intensive_agreement",
                          return_value=None):
            with self.assertRaisesRegex(RuntimeError,
                                        "audio_consensus_alass_ffsubsync_disagree"):
                promote.audio_consensus(Path(film()["host_path"]),b"original",5400)

    def test_audio_consensus_rejects_unverified_ffsubsync_correction(self):
        with patch.object(promote.gate,"validate_srt",return_value={}), \
             patch.object(promote.ff,"keep_source_dialogue",
                          side_effect=lambda _,candidate:candidate), \
             patch.object(promote.alass,"align",
                          return_value=(b"ALASS","video_audio")), \
             patch.object(promote.alass,"assess",return_value={}), \
             patch.object(promote.ff,"align_in_container",
                          return_value=b"FFSUBSYNC"), \
             patch.object(promote.ff,"repair_minor_overlaps",
                          return_value=(b"FFSUBSYNC",{})), \
             patch.object(promote.ff,"check_alignment",
                          side_effect=RuntimeError("ffsubsync_shift_or_variation_excessive")), \
             patch.object(promote.alass,"_intensive_agreement") as agree:
            with self.assertRaisesRegex(RuntimeError,
                                        "ffsubsync_shift_or_variation_excessive"):
                promote.audio_consensus(Path(film()["host_path"]),b"original",5400)
            agree.assert_not_called()

    def test_missing_english_reference_falls_back_before_staging(self):
        row=film()
        evidence={"alignment_reference":"video_audio",
                  "audio_engine_consensus":"ffsubsync_video_audio",
                  "audio_consensus_thirds":[0.96,0.97,0.99]}
        with patch.object(promote.gate,"safe_media_path",
                          return_value=Path(row["host_path"])), \
             patch.object(promote.gate,"subprocess_duration",return_value=5400), \
             patch.object(promote.gate,"ffprobe_streams",return_value=([],None)), \
             patch.object(promote.gate,"check_no_existing_ja"), \
             patch.object(promote.alass,"intensive_align",
                          side_effect=RuntimeError(
                              "alass_intensive_missing_english_reference")), \
             patch.object(promote,"audio_consensus",
                          return_value=(b"ALASS",evidence)) as audio, \
             patch.object(promote.ff,"keep_source_dialogue",
                          return_value=b"ALASS"), \
             patch.object(promote.alass,"assess",
                          return_value={"mode":"aligned"}) as assess:
            output,proof,decision=promote.cross_check(
                row,saved(),b"original",5400)
        self.assertEqual(output,b"ALASS")
        self.assertEqual(proof,evidence)
        self.assertEqual(decision["mode"],"aligned")
        audio.assert_called_once()
        self.assertFalse(assess.call_args.kwargs["independently_verified_tail"])

    def test_disagreeing_english_never_falls_back_to_audio(self):
        row=film()
        with patch.object(promote.gate,"safe_media_path",
                          return_value=Path(row["host_path"])), \
             patch.object(promote.gate,"subprocess_duration",return_value=5400), \
             patch.object(promote.gate,"ffprobe_streams",return_value=([],None)), \
             patch.object(promote.gate,"check_no_existing_ja"), \
             patch.object(promote.alass,"intensive_align",
                          side_effect=RuntimeError(
                              "alass_intensive_no_independent_reference_agreement")), \
             patch.object(promote,"audio_consensus") as fallback:
            with self.assertRaisesRegex(RuntimeError,
                                        "alass_intensive_no_independent_reference_agreement"):
                promote.cross_check(row,saved(),b"original",5400)
            fallback.assert_not_called()

    def test_audio_consensus_publication_disallows_tail_exception(self):
        row=film()
        c=saved()
        evidence={"alignment_reference":"video_audio",
                  "audio_engine_consensus":"ffsubsync_video_audio",
                  "audio_consensus_thirds":[0.97,0.95,0.98]}
        ready={"chosen":b"aligned","assessment":{"mode":"aligned"},
               "row":row,"video":Path(row["host_path"]),
               "target":Path(row["host_path"]+".ja.srt")}
        with patch.object(promote.review,"acceptable",return_value=True), \
             patch.object(promote,"identity_ok",return_value=True), \
             patch.object(promote,"read_receipt",return_value=receipt()), \
             patch.object(promote.stage,"duration_if_safe",return_value=5400), \
             patch.object(promote,"cached_source",return_value=(
                 b"source",{"cues":100,"japanese_characters":1500,
                            "japanese_cue_fraction":0.9})), \
             patch.object(promote,"cross_check",
                          return_value=(b"aligned",evidence,{})), \
             patch.object(promote,"stage_cached_opensubtitles",
                          return_value="123456"), \
             patch.object(promote.alass,"prepare",
                          return_value=ready) as prepare, \
             patch.object(promote.alass,"preserve") as preserve, \
             patch.object(promote.gate,"publish") as publish, \
             patch.object(promote.queue,"mark_completed"):
            result,_=promote.promote(row,c)
        self.assertEqual(result,"published")
        self.assertFalse(prepare.call_args.kwargs["independently_verified_tail"])
        self.assertEqual(ready["assessment"]["engine"],
                         "review_alass_ffsubsync_audio_consensus_v1")
        preserve.assert_called_once()
        publish.assert_called_once()

    def test_no_stage_or_publication_when_cross_check_refuses(self):
        row=film()
        c=saved()
        with patch.object(promote.review,"acceptable",return_value=True), \
             patch.object(promote,"identity_ok",return_value=True), \
             patch.object(promote,"read_receipt",return_value=receipt()), \
             patch.object(promote.stage,"duration_if_safe",return_value=5400), \
             patch.object(promote,"cached_source",return_value=(
               b"source",{"cues":180,"japanese_characters":1500,
                          "japanese_cue_fraction":0.9})), \
             patch.object(promote,"cross_check",
                          side_effect=RuntimeError("no_independent_reference")), \
             patch.object(promote,"stage_cached_opensubtitles") as stage, \
             patch.object(promote.gate,"publish") as publish, \
             patch.object(promote.alass,"preserve") as save:
            with self.assertRaisesRegex(RuntimeError,"no_independent_reference"):
                promote.promote(row,c)
            stage.assert_not_called()
            publish.assert_not_called()
            save.assert_not_called()

    def test_publication_uses_existing_alass_and_no_overwrite_gate(self):
        row=film()
        c=saved()
        evidence={
            "alignment_reference":"same_video_embedded_english",
            "intensive_cross_reference":"video_audio",
            "intensive_agreement_thirds":[0.93,0.94,0.95]}
        ready={
            "chosen":b"aligned","assessment":{"mode":"aligned"},
            "row":row,"video":Path(row["host_path"]),
            "target":Path(row["host_path"]+".ja.srt")}
        with patch.object(promote.review,"acceptable",return_value=True), \
             patch.object(promote,"identity_ok",return_value=True), \
             patch.object(promote,"read_receipt",return_value=receipt()), \
             patch.object(promote.stage,"duration_if_safe",return_value=5400), \
             patch.object(promote,"cached_source",return_value=(
                 b"source",{"cues":180,"japanese_characters":1500,
                            "japanese_cue_fraction":0.9})), \
             patch.object(promote,"cross_check",return_value=(
                 b"aligned",evidence,{})), \
             patch.object(promote,"stage_cached_opensubtitles",
                          return_value="123456") as stage, \
             patch.object(promote.alass,"prepare",return_value=ready) as prepare, \
             patch.object(promote.alass,"preserve") as preserve, \
             patch.object(promote.gate,"publish") as publish, \
             patch.object(promote.queue,"mark_completed") as mark:
            result,_=promote.promote(row,c)
            self.assertEqual(result,"published")
            stage.assert_called_once()
            self.assertEqual(prepare.call_args.kwargs["independently_verified_tail"],True)
            preserve.assert_called_once_with(ready)
            publish.assert_called_once()
            mark.assert_called_once_with(row["jellyfin_id"])


if __name__=="__main__":
    unittest.main()
