"""Offline regressions for exhaustive source-first selection and fail-closed AI."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from tools import subhub_deep_source as deep


class DeepSourceTests(unittest.TestCase):
    JID="a"*32

    def row(self, path):
        return {"jellyfin_id":self.JID,"kind":"Movie","title":"Example Film",
                "year":2024,"host_path":str(path),"status":"ready_ja_search"}

    def search(self):
        return {"_outcome":"plausible","_searched_at":int(time.time()),
                "provider_gates":{"opensubtitles":"ok","subdl":"ok"},
                "incomplete_providers":[],"candidates":[]}

    def test_publisher_held_reason_is_not_suppressed(self):
        from contextlib import redirect_stdout
        from io import StringIO
        out=StringIO()
        receipt={"jellyfin_id":self.JID,"result":"held",
                 "reason":"RuntimeError: alass_out_of_video"}
        with mock.patch.object(deep,"call",return_value=(0,
                "BRUISER_PUBLISH_ITEM: "+json.dumps(receipt),"")), \
             redirect_stdout(out):
            self.assertEqual(deep.publish(self.JID), "held")
        self.assertIn("DEEP_SOURCE_PUBLISH_HELD:",out.getvalue())
        self.assertIn("alass_out_of_video",out.getvalue())

    def test_incomplete_held_is_retry_but_logs_underlying_reason(self):
        from contextlib import redirect_stdout
        from io import StringIO
        out=StringIO()
        receipt={"jellyfin_id":self.JID,"result":"held",
                 "reason":"RuntimeError: no_candidate_passed_trusted_sync_correction"}
        report=("TITLE_FAILURE_NOT_CACHED: pending source check\n"
                "BRUISER_PUBLISH_ITEM: "+json.dumps(receipt))
        with mock.patch.object(deep,"call",return_value=(0,report,"")), \
             redirect_stdout(out):
            self.assertEqual(deep.publish(self.JID),"retry")
        self.assertIn("cause=incomplete_engine_validation",out.getvalue())
        self.assertIn("no_candidate_passed_trusted_sync_correction",out.getvalue())

    def test_failed_publisher_without_receipt_is_retriable_not_exhausted(self):
        from contextlib import redirect_stdout
        from io import StringIO
        out=StringIO()
        with mock.patch.object(deep,"call",return_value=(2,"","failure")), \
             redirect_stdout(out):
            self.assertEqual(deep.publish(self.JID),"retry")
        self.assertIn("cause=nonzero_exit",out.getvalue())

    def test_deferred_provider_never_proves_exhaustion(self):
        doc=self.search()
        self.assertTrue(deep.search_complete(doc))
        doc["provider_gates"]["subdl"]="cooldown"
        self.assertFalse(deep.search_complete(doc))
        doc=self.search()
        doc["incomplete_providers"]=["subdl"]
        self.assertFalse(deep.search_complete(doc))
        doc=self.search()
        doc["_outcome"]="partial"
        self.assertFalse(deep.search_complete(doc))
        doc=self.search()
        doc["_searched_at"]-=32*86400
        self.assertFalse(deep.search_complete(doc))
        doc=self.search()
        del doc["provider_gates"]["opensubtitles"]
        self.assertFalse(deep.search_complete(doc))

    def test_less_popular_valid_releases_are_not_discarded(self):
        row=self.row("/tmp/example.mkv")
        doc=self.search()
        doc["candidates"]=[
            {"provider":"opensubtitles","subtitle_id":"1000",
             "score":95,"grade":"plausible"},
            {"provider":"opensubtitles","subtitle_id":"2000",
             "score":3,"grade":"plausible"},
            {"provider":"subdl","subtitle_id":"release003",
             "score":5,"grade":"review"},
            {"provider":"opensubtitles","subtitle_id":"9999",
             "score":999,"grade":"reject","filename":"Other Movie"}]
        def valid(r,c):
            return c["subtitle_id"]!="9999"
        with mock.patch.object(deep.stage,"identity_ok",side_effect=valid), \
             mock.patch.object(deep.subdl,"identity_ok",return_value=True), \
             mock.patch.object(deep.rank,"release_match",return_value=0):
            ranked=deep.candidates_for(row,doc)
        self.assertEqual([c["subtitle_id"] for c in ranked],
                         ["1000","2000","release003"])

    def test_held_candidate_triggers_next_saved_release(self):
        with tempfile.TemporaryDirectory() as root:
            video=Path(root)/"Example Film 2024.mkv"
            video.write_bytes(b"video")
            doc=self.search()
            doc["candidates"]=[{"provider":"opensubtitles",
                "subtitle_id":"1000"},{"provider":"opensubtitles","subtitle_id":"2000"}]
            row=self.row(video)
            calls=[]
            def stage_one(jid,c):
                calls.append(c["subtitle_id"])
                return "staged","ok"
            with mock.patch.object(deep.inventory,"load_latest_manifest",
                                   return_value=[row]), \
                 mock.patch.object(deep.stage,"japanese_sidecar_exists",
                                   return_value=False), \
                 mock.patch.object(deep,"search_record",return_value=doc), \
                 mock.patch.object(deep,"repair_staged",
                                   side_effect=["held","held","covered"]), \
                 mock.patch.object(deep,"candidates_for",
                                   return_value=doc["candidates"]), \
                 mock.patch.object(deep,"stage_one",side_effect=stage_one), \
                 mock.patch.object(deep,"save_exhausted") as saved:
                output=deep.run(self.JID)
            self.assertEqual(output["result"],"covered")
            self.assertEqual(calls,["1000","2000"])
            saved.assert_not_called()

    def test_quota_paused_source_never_dispatches_plamo(self):
        with tempfile.TemporaryDirectory() as root:
            video=Path(root)/"Example Film 2024.mkv"
            video.write_bytes(b"video")
            row=self.row(video)
            doc=self.search()
            found=[{"provider":"opensubtitles","subtitle_id":"1000"}]
            with mock.patch.object(deep.inventory,"load_latest_manifest",
                                   return_value=[row]), \
                 mock.patch.object(deep.stage,"japanese_sidecar_exists",
                                   return_value=False), \
                 mock.patch.object(deep,"search_record",return_value=doc), \
                 mock.patch.object(deep,"repair_staged",return_value="held"), \
                 mock.patch.object(deep,"candidates_for",return_value=found), \
                 mock.patch.object(deep,"stage_one",
                                   return_value=("retry","provider_quota")), \
                 mock.patch.object(deep,"save_exhausted") as saved:
                output=deep.run(self.JID)
            self.assertEqual(output["result"],"retry_source")
            saved.assert_not_called()

    def test_completed_no_match_can_be_handed_to_plamo(self):
        with tempfile.TemporaryDirectory() as root:
            video=Path(root)/"Example Film 2024.mkv"
            video.write_bytes(b"video")
            row=self.row(video)
            doc=self.search()
            doc["_outcome"]="none"
            with mock.patch.object(deep.inventory,"load_latest_manifest",
                                   return_value=[row]), \
                 mock.patch.object(deep.stage,"japanese_sidecar_exists",
                                   return_value=False), \
                 mock.patch.object(deep,"search_record",return_value=doc), \
                 mock.patch.object(deep,"repair_staged",return_value="held"), \
                 mock.patch.object(deep,"save_exhausted") as saved:
                result=deep.run(self.JID)
            self.assertEqual(result["result"],"plamo")
            saved.assert_called_once()


if __name__=="__main__":
    unittest.main()
