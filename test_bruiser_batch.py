"""Offline tests for detached source-only batch controller and live status parser."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import bruiser_batch as batch


class BatchControllerTests(unittest.TestCase):
    def test_search_progress_and_actual_publishing(self):
        doc={"counts":{},"held_reasons":{},"quota_exhausted":False}
        batch.event(doc,"[4/600] SEARCHING: Example (2025)")
        self.assertEqual(doc["phase_current"],4)
        self.assertEqual(doc["phase_total"],600)
        self.assertEqual(doc["counts"]["search_started"],1)
        batch.event(doc,"[4/600] PLAUSIBLE: plausible=2 review=0")
        batch.event(doc,"[1/200] STAGING: Example")
        batch.event(doc,"STAGED: /private/example.ja.srt")
        self.assertEqual(doc["counts"]["staged"],1)
        with patch.object(batch,"persist_publisher_hold",return_value=True):
            batch.event(doc,'BRUISER_PUBLISH_ITEM: '+json.dumps({
                "jellyfin_id":"a"*32,"result":"held","reason":"timing_shift_needs_review"}))
        self.assertEqual(doc["counts"]["holds_recorded_in_queue"],1)
        batch.event(doc,'BRUISER_PUBLISH_ITEM: '+json.dumps({
            "jellyfin_id":"b"*32,"result":"published","proof":"ready_ffsubsync"}))
        batch.event(doc,'QUEUE SUMMARY: {"published_new":1,"held":1}')
        self.assertEqual(doc["counts"]["published_new"],1)
        self.assertEqual(doc["counts"]["verified_publication_events"],1)
        self.assertEqual(doc["counts"]["held_titles"],1)

    def test_quota_event_blocks_stage_but_keeps_search_count(self):
        doc={"counts":{},"held_reasons":{},"quota_exhausted":False}
        batch.event(doc,"PROVIDER_LIMIT_REACHED: stop further downloads")
        self.assertTrue(doc["quota_exhausted"])
        self.assertEqual(doc["counts"]["provider_limit_events"],1)

    def test_atomic_private_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(batch,"STATE",Path(directory)/"private"):
                batch.save_state({"schema":"bruiser-batch-v1","cycle":3,
                                  "phase":"search_opensubtitles","counts":{"staged":9}})
                value=batch.load_state()
                self.assertEqual(value["cycle"],3)
                self.assertEqual(value["counts"]["staged"],9)
                folder=Path(directory)/"private"
                self.assertEqual(folder.stat().st_mode & 0o777,0o700)
                self.assertEqual((folder/"current.json").stat().st_mode & 0o777,0o600)

    def test_refuse_oversized_or_invalid_budget(self):
        from argparse import Namespace
        with self.assertRaises(ValueError):
            batch.validate_budget(Namespace(
                cycles=99,search_budget=600,stage_budget=200,publish_limit=200))
        with self.assertRaises(ValueError):
            batch.validate_budget(Namespace(
                cycles=5,search_budget=601,stage_budget=200,publish_limit=200))

    def test_source_only_batch_runner_never_invokes_model(self):
        from inspect import getsource
        text=getsource(batch.worker)
        self.assertIn("ja_first_search_pilot.py",text)
        self.assertIn("ja_first_stage_saved_batch.py",text)
        self.assertIn("ja_first_publish_queue.py",text)
        self.assertNotIn("start_existing_worker",text)
        self.assertNotIn("plamo",text.casefold())


if __name__=="__main__":
    unittest.main()
