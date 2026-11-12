"""A completion job reports its own nested source checkpoints, not stale jobs."""
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tools import subhub_dashboard_server as d


class FinishScopeProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        root.chmod(0o700)
        self.source=root/"jellyfin-source-batch.json"
        self.finish=root/"finish-scope.json"
        self.now=int(time.time())
        self.series="It's Always Sunny in Philadelphia"
        self.seasons=[1,9]
        self.finish_doc={
            "schema":"subhub-finish-scope-v1",
            "series":self.series,
            "seasons":self.seasons,
            "phase":"source","state":"running",
            "before":{"missing":23,"covered":156},
            "updated_utc":datetime.fromtimestamp(
                self.now-4,timezone.utc).isoformat()}
        self.source_doc={
            "schema":"jellyfin-source-batch-v1",
            "selector":{"series":self.series,
                        "seasons":self.seasons,"picks":[]},
            "started_at":self.now-2,"updated_at":self.now-1,
            "state":"queued",
            "phase":"sublarr_search",
            "current":"S18E01 Frank Marries a Corpse",
            "pass_total":23,"pass_processed":17,
            "searches_this_run":28,"downloads_this_run":5,
            "items":[{"status":"published"} for _ in range(3)]+
                    [{"status":"held"} for _ in range(2)]+
                    [{"status":"no_match"} for _ in range(12)]+
                    [{"status":"queued"} for _ in range(6)]}
        self._write(self.finish,self.finish_doc)
        self._write(self.source,self.source_doc)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self,path,obj):
        path.write_text(json.dumps(obj))
        path.chmod(0o600)

    def test_live_worker_reports_processed_separately_from_published(self):
        with patch.object(d,"JELLYFIN_SOURCE_STATE",self.source), \
             patch.object(d.finish_scope,"STATE",self.finish), \
             patch.object(d,"unit_active",return_value=True):
            status=d.finish_scope_status()
        p=status["source_progress"]
        self.assertTrue(status["active"])
        self.assertEqual(status["phase"],"source")
        self.assertEqual(p["processed"],17)
        self.assertEqual(p["total"],23)
        self.assertEqual(p["published"],3)
        self.assertEqual(p["searches"],28)
        self.assertEqual(p["downloads"],5)
        self.assertIn("Frank Marries",p["current"])
        self.assertLess(p["age_seconds"],30)

    def test_old_scope_or_old_job_is_not_shown(self):
        for change in ({"started_at":self.now-300},
                       {"selector":{"series":"Another Show",
                                    "seasons":[1,9],"picks":[]}}):
            source=dict(self.source_doc,**change)
            self._write(self.source,source)
            with self.subTest(change=change), \
                 patch.object(d,"JELLYFIN_SOURCE_STATE",self.source):
                self.assertIsNone(d.finish_source_progress(self.finish_doc))

    def test_inactive_finish_job_does_not_claim_live_progress(self):
        with patch.object(d,"JELLYFIN_SOURCE_STATE",self.source), \
             patch.object(d.finish_scope,"STATE",self.finish), \
             patch.object(d,"unit_active",return_value=False):
            status=d.finish_scope_status()
        self.assertFalse(status["active"])
        self.assertEqual(status["state"],"interrupted")
        self.assertNotIn("source_progress",status)


if __name__=="__main__":
    unittest.main()
