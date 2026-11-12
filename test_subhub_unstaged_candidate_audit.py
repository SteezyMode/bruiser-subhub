"""Offline checks for read-only historical unstaged JA candidate batch triage."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch

from tools import subhub_unstaged_candidate_audit as audit


class UnstagedAuditTests(unittest.TestCase):
    def stagers(self):
        o=SimpleNamespace(
            identity_ok=Mock(side_effect=lambda row,c: c.get("valid",True)),
            known_rejected_download=Mock(return_value=False),
            japanese_sidecar_exists=Mock(return_value=False),
            alternate_ready=Mock(return_value=True),
            duration_if_safe=Mock(return_value=6123.0),
            priorities=SimpleNamespace(
                queue_position=Mock(return_value=(100,0))))
        s=SimpleNamespace(
            identity_ok=Mock(side_effect=lambda row,c:c.get("valid",True)),
            numeric_id=Mock(return_value=("9000000","digest")))
        return o,s

    def test_classifies_distinct_providers_without_downloading(self):
        os,dl=self.stagers()
        saved=[
            {"provider":"opensubtitles","subtitle_id":"123456",
             "grade":"plausible","filename":"Movie.2020.ja"},
            {"provider":"subdl","subtitle_id":"some_release",
             "grade":"review","filename":"Movie 2020"},
            {"provider":"opensubtitles","subtitle_id":"123456",
             "grade":"plausible"},
            {"provider":"other","subtitle_id":"not_supported"},
        ]
        found,excluded,_=audit.evaluate_candidates(
            {"kind":"Movie","title":"Movie","year":2020},saved,os,dl,[])
        self.assertEqual(len(found),2)
        self.assertEqual({c["provider"] for c in found},
                         {"opensubtitles","subdl"})
        self.assertEqual(excluded["duplicate_provider_result"],1)
        self.assertEqual(excluded["provider_not_supported_by_stage"],1)
        os.known_rejected_download.assert_called_once()

    def test_unverified_search_hit_not_stageable(self):
        os,dl=self.stagers()
        os.identity_ok.side_effect=lambda row,candidate:False
        found,reasons,examples=audit.evaluate_candidates(
            {},[{"provider":"opensubtitles","subtitle_id":"99999",
                 "filename":"Wrong.Film"}],os,dl,[])
        self.assertEqual(found,[])
        self.assertEqual(reasons["stage_identity_not_established"],1)
        self.assertIn("not_stage_identity",examples[0]["reason"])
        os.known_rejected_download.assert_not_called()

    def test_cached_failed_download_is_not_retried_as_eligible(self):
        os,dl=self.stagers()
        os.known_rejected_download.return_value=True
        found,reasons,_=audit.evaluate_candidates(
            {},[{"provider":"opensubtitles","subtitle_id":"99999"}],
            os,dl,[])
        self.assertEqual(found,[])
        self.assertEqual(reasons["previously_downloaded_bytes_rejected"],1)

    def test_subdl_only_requires_separate_route_after_preflight(self):
        os,dl=self.stagers()
        with tempfile.TemporaryDirectory() as temp:
            video=Path(temp)/"Film.mkv"
            video.write_bytes(b"placeholder")
            row={"status":"ready_ja_search","host_path":str(video)}
            selected=[{"provider":"subdl","subtitle_id":"release_01"}]
            state,detail=audit.current_status(row,selected,[],os,{} ,{})
            self.assertEqual(state,"stageable_subdl_separate_route")
            self.assertEqual(detail,"not_selected_by_opensubtitles_batch")
            os.duration_if_safe.assert_called_once()

    def test_covered_sidecar_precedes_any_download(self):
        os,dl=self.stagers()
        with tempfile.TemporaryDirectory() as temp:
            video=Path(temp)/"Film.mkv"
            video.write_bytes(b"placeholder")
            os.japanese_sidecar_exists.return_value=True
            state,_=audit.current_status(
                {"status":"ready_ja_search","host_path":str(video)},
                [{"provider":"opensubtitles"}],[],os,{}, {})
        self.assertEqual(state,"already_covered_by_sidecar")
        os.duration_if_safe.assert_not_called()

    def test_queue_inactive_or_video_missing_stays_unstageable(self):
        os,dl=self.stagers()
        with tempfile.TemporaryDirectory() as temp:
            video=Path(temp)/"Film.mkv"
            video.write_bytes(b"placeholder")
            os.priorities.queue_position.return_value=None
            row={"status":"ready_ja_search","host_path":str(video)}
            state,_=audit.current_status(
                row,[{"provider":"opensubtitles"}],[],os,{}, {})
            self.assertEqual(state,"coverage_queue_not_selectable")
            video.unlink()
            state,_=audit.current_status(
                row,[{"provider":"opensubtitles"}],[],os,{}, {})
            self.assertEqual(state,"media_unavailable")

    def test_staged_record_now_present_supersedes_old_failure_snapshot(self):
        os,dl=self.stagers()
        with tempfile.TemporaryDirectory() as temp:
            video=Path(temp)/"Film.mkv"
            video.write_bytes(b"placeholder")
            state,_=audit.current_status(
                {"status":"ready_ja_search","host_path":str(video)},
                [{"provider":"opensubtitles"}],
                [{"subtitle_id":"111","status":"staged"}],os,{}, {})
            self.assertEqual(state,"staging_progress_changed")


if __name__=="__main__":
    unittest.main()
