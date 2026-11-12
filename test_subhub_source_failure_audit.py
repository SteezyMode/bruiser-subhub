"""One-time source-failure audit: offline classification, no writes."""
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from tools import subhub_source_failure_audit as audit


def search(candidates=(), rejected=(), gates=None, outcome="plausible"):
    return {"outcome":outcome,"results":{
        "candidates":list(candidates),"rejected_candidates":list(rejected),
        "provider_gates":gates or {"opensubtitles":"ok","subdl":"ok"},
        "incomplete_providers":[]}}


class SourceFailureAuditTests(unittest.TestCase):
    JID="a"*32

    def test_staged_japanese_samples_from_real_srt_remain_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            stage=root/"staged"
            stage.mkdir()
            subtitle=stage/"example.ja.srt"
            subtitle.write_text(
                "1\n00:00:01,000 --> 00:00:03,000\nこんにちは\n\n"
                "2\n00:01:01,000 --> 00:01:03,000\nもう一度\n\n"
                "3\n00:02:01,000 --> 00:02:03,000\nさようなら\n",
                encoding="utf-8")
            saved=subtitle.read_bytes()
            with patch.object(audit,"ROOT",root):
                samples=audit._sample_srt(subtitle)
                self.assertEqual(len(samples),3)
                self.assertIn("こんにちは",samples[0])
                self.assertIn("もう一度",samples[1])
                self.assertIn("さようなら",samples[2])
            self.assertEqual(subtitle.read_bytes(),saved)

    def test_provider_incomplete_never_claimed_no_results(self):
        r=search(outcome="none",gates={
            "opensubtitles":"ok","subdl":"cooldown"})
        row={"title":"Example Movie","audio_language":"eng",
             "status":"ready_ja_search"}
        self.assertEqual(audit.describe(self.JID,row,r,[])["reason"],
                         "provider_coverage_not_proven")

    def test_staged_releases_are_synchronization_salvage_group(self):
        row={"title":"Example Movie","status":"ready_ja_search"}
        r=search(candidates=[{"provider":"opensubtitles",
                              "subtitle_id":"1234","score":3}])
        stage=[{"subtitle_id":"1234","status":"staged","provider":"opensubtitles"}]
        result=audit.describe(self.JID,row,r,stage)
        self.assertEqual(result["reason"],
                         "japanese_candidates_staged_but_unpublished")
        self.assertEqual(result["candidate_count"],1)
        self.assertEqual(result["stage_count"],1)

    def test_provider_no_results_is_distinct_from_candidate_not_staged(self):
        row={"title":"Example Movie","status":"ready_ja_search"}
        self.assertEqual(audit.describe(
            self.JID,row,search(candidates=[
                {"provider":"subdl","subtitle_id":"777"}]),[])["reason"],
            "japanese_candidates_found_not_staged")
        self.assertEqual(audit.describe(
            self.JID,row,search(outcome="none"),[])["reason"],
            "no_saved_credible_japanese_results")

    def test_existing_audio_coverage_is_flagged_for_review(self):
        row={"title":"Japanese Film","status":"japanese_audio",
             "audio_language":"jpn"}
        self.assertEqual(audit.describe(
            self.JID,row,search(outcome="none"),[])["reason"],
            "already_covered_in_inventory")

    def test_journal_requeue_not_sent_to_plamo(self):
        events=[
            {"MESSAGE":"FINISH_PLAMO_QUEUE: "+self.JID+
                       " Japanese sources exhausted"},
            {"MESSAGE":"FINISH_SOURCE_REQUEUE: "+self.JID},
            {"MESSAGE":"FINISH_PLAMO_QUEUE: "+"b"*32},
        ]
        ids,states=audit.final_plamo(events)
        self.assertEqual(ids,{"b"*32})
        self.assertEqual(states[self.JID],"SOURCE_REQUEUE")

    def test_full_audit_never_uses_uncorroborated_count_as_movie_names(self):
        events=[{"MESSAGE":"FINISH_PLAMO_QUEUE: "+self.JID}]
        result=audit.analyze(
            {"total_exact_files":679,"plamo_pending":191},
            {self.JID:{"title":"Example Movie","status":"ready_ja_search"}},
            {self.JID:search(outcome="none")},{},events)
        self.assertFalse(result["journal_complete_for_queue"])
        self.assertEqual(result["plamo_ids_reconstructed"],1)


if __name__=="__main__":
    unittest.main()
