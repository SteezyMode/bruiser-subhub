"""Offline quota accounting: real downloads, not guessed provider limits."""
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import subhub_download_ledger as ledger
from tools import ja_first_stage_saved_batch as native_stage
from tools import subhub_dashboard_server as dashboard


class DailyDownloadLedger(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root=Path(self.folder.name)
        os.chmod(root,0o700)
        self.path=root/"downloads.sqlite3"

    def test_combined_per_provider_and_failed_pending_do_not_count_as_success(self):
        now=int(time.time())
        a=ledger.begin("opensubtitles","jellyfin_subbuzz",at=now,path=self.path)
        ledger.finish(a,"downloaded",byte_count=25989,path=self.path)
        b=ledger.begin("subdl","jellyfin_subbuzz",at=now,path=self.path)
        ledger.finish(b,"downloaded",byte_count=1120,path=self.path)
        c=ledger.begin("opensubtitles","sublarr_native",at=now,path=self.path)
        ledger.finish(c,"quota_blocked",error_kind="HTTP_429",path=self.path)
        d=ledger.begin("unknown","jellyfin_native",at=now,path=self.path)
        e=ledger.begin("yify","jellyfin_subbuzz",at=now,path=self.path)
        ledger.finish(e,"failed",error_kind="HTTP_500",path=self.path)
        report=ledger.summary(at=now,path=self.path)
        today=report["today"]
        self.assertEqual(today["attempted"],5)
        self.assertEqual(today["downloaded"],2)
        self.assertEqual(today["quota_blocked"],1)
        self.assertEqual(today["failed"],1)
        self.assertEqual(today["pending"],1)
        self.assertEqual(today["providers"]["opensubtitles"]["downloaded"],1)
        self.assertEqual(today["providers"]["subdl"]["downloaded"],1)
        self.assertIsNone(report["quota_limit"])
        self.assertIsNone(report["quota_reset"])
        self.assertFalse(report["account_wide_total_known"])
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        with self.assertRaisesRegex(RuntimeError,"already_closed"):
            ledger.finish(a,"downloaded",byte_count=25989,path=self.path)

    def test_japan_midnight_uses_reporting_calendar_not_fake_provider_reset(self):
        before=int(datetime(2026,11,10,14,59,tzinfo=timezone.utc).timestamp())
        after=int(datetime(2026,11,10,15,1,tzinfo=timezone.utc).timestamp())
        ledger.record_completed("opensubtitles","sublarr_native",100,
                                at=before,path=self.path)
        ledger.record_completed("opensubtitles","jellyfin_subbuzz",200,
                                at=after,path=self.path)
        summary=ledger.summary(at=after,path=self.path)
        self.assertEqual(summary["today"]["downloaded"],1)
        self.assertEqual(summary["recent_days"][1]["downloaded"],1)
        self.assertEqual(summary["calendar"],"Asia/Tokyo")
        self.assertIsNone(summary["quota_reset"])

    def test_subbuzz_backend_is_attributed_only_when_id_proves_provider(self):
        self.assertEqual(ledger.jellyfin_provider({
            "ProviderName":"subbuzz","Id":"subbuzz_opensubtitles.comXYZ"}),
            "opensubtitles")
        self.assertEqual(ledger.jellyfin_provider({
            "ProviderName":"subbuzz","Id":"subbuzz_subdl.comXYZ"}),"subdl")
        self.assertEqual(ledger.jellyfin_provider({
            "ProviderName":"subbuzz","Id":"opaque-data"}),"unknown")
        self.assertEqual(ledger.jellyfin_provider({
            "ProviderName":"Open Subtitles","Id":"opaque-data"}),"opensubtitles")

    def test_bad_private_root_and_raw_secret_kind_refused(self):
        with tempfile.TemporaryDirectory() as d:
            bad=Path(d)
            os.chmod(bad,0o755)
            with self.assertRaisesRegex(RuntimeError,"private_directory_invalid"):
                ledger.begin("opensubtitles","jellyfin_native",path=bad/"u.sqlite3")
        with self.assertRaises(ValueError):
            ledger.begin("arbitrary-provider","jellyfin_native",path=self.path)
        attempt=ledger.begin("unknown","other",path=self.path)
        with self.assertRaises(ValueError):
            ledger.finish(attempt,"failed",
                          error_kind="Authorization: Bearer secret",path=self.path)

    def test_owner_dashboard_uses_readonly_ledger_and_observed_totals(self):
        ledger.record_completed("opensubtitles","jellyfin_subbuzz",29000,
                                path=self.path)
        with patch.object(dashboard,"DOWNLOAD_LEDGER_DB",self.path):
            result=dashboard.download_ledger_status()
        self.assertTrue(result["available"])
        self.assertEqual(result["today_downloaded"],1)
        self.assertEqual(result["today_attempted"],1)
        self.assertEqual(result["providers"]["opensubtitles"]["downloaded"],1)
        self.assertIsNone(result["quota_limit"])
        self.assertEqual(len(result["recent_days"]),7)

    def test_native_worker_get_counts_success_before_qa_failure(self):
        # Provider returned bytes; the downloaded subtitle was rejected later.
        # It still consumes a download and must count in the combined day.
        stdout=("SUBHUB_DOWNLOAD_REQUEST: opensubtitles\n"
                "SUBHUB_DOWNLOAD_RECEIVED: 12345\n"
                'STAGE_RESULT_JSON:{"result":"blocked","error":"too_few_subtitle_cues"}\n')
        native_stage.record_native_download_attempt(
            stdout,{"result":"blocked","error":"too_few_subtitle_cues"},
            path=self.path)
        today=ledger.summary(path=self.path)["today"]
        self.assertEqual(today["attempted"],1)
        self.assertEqual(today["downloaded"],1)
        self.assertEqual(today["failed"],0)

    def test_native_quota_block_and_other_failure_are_recorded(self):
        request="SUBHUB_DOWNLOAD_REQUEST: opensubtitles\n"
        native_stage.record_native_download_attempt(
            request,{"result":"blocked","error":"HTTP_429 Too Many Requests"},
            path=self.path)
        native_stage.record_native_download_attempt(
            request,{"result":"blocked","error_type":"ConnectionError"},
            path=self.path)
        # Cache hit did not issue a remote request; do not count it.
        native_stage.record_native_download_attempt(
            'STAGE_RESULT_JSON:{"result":"already_staged"}',
            {"result":"already_staged"},path=self.path)
        today=ledger.summary(path=self.path)["today"]
        self.assertEqual(today["attempted"],2)
        self.assertEqual(today["downloaded"],0)
        self.assertEqual(today["quota_blocked"],1)
        self.assertEqual(today["failed"],1)

    def test_native_worker_missing_result_still_accounts_for_get(self):
        native_stage.record_native_download_attempt(
            "SUBHUB_DOWNLOAD_REQUEST: opensubtitles\n",{},path=self.path)
        today=ledger.summary(path=self.path)["today"]
        self.assertEqual(today["attempted"],1)
        self.assertEqual(today["failed"],1)

    def test_dashboard_has_daily_combined_quota_visible(self):
        html=(Path(__file__).parent/"tools/subhub_dashboard.html").read_text()
        for needle in ('id="download-today"','id="download-providers"',
                       'id="download-history"','renderDownloadUsage(d)'):
            self.assertIn(needle,html)


if __name__=="__main__":
    unittest.main()
