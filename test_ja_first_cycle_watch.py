"""Offline regression: UI tracker attaches without starting/interrupting a job."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import ja_first_cycle as controller


class ControllerWatchTests(unittest.TestCase):
    def test_watch_is_read_only_no_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/"subhub_live_tracker.py").write_text("# stub\n")
            calls=[]
            with patch.object(controller.subprocess,"call",
                              side_effect=lambda args,**kw: calls.append((args,kw)) or 0):
                result=controller.watch(folder,job_id="daily-sample-film",interval=10)
            self.assertEqual(result,0)
            self.assertEqual(len(calls),1)
            self.assertIn("--watch",calls[0][0])
            self.assertEqual(calls[0][0][-2:],["--job-id","daily-sample-film"])
            self.assertIn("subhub_live_tracker.py",calls[0][0][2])

    def test_read_only_watch_dispatch_does_not_require_apply(self):
        calls=[]
        with patch.object(controller,"watch",
                          side_effect=lambda *a,**k:calls.append(k)):
            controller.main(["watch","--interval","5"])
        self.assertEqual(calls,[{"interval":5}])

    def test_start_and_watch_pins_exact_started_job(self):
        calls=[]
        jid="daily-pinned-sample"
        with patch.object(controller,"start_existing_worker",return_value=jid):
            with patch.object(controller,"watch",
                              side_effect=lambda *a,**k:calls.append(k)):
                controller.main(["start-worker","--apply","--watch"])
        self.assertEqual(calls,[{"job_id":jid,"interval":10}])

    def test_start_does_not_watch_if_no_pending_job(self):
        with patch.object(controller,"start_existing_worker",return_value=None):
            with patch.object(controller,"watch",
                              side_effect=AssertionError("no worker means no watch")):
                controller.main(["start-worker","--apply","--watch"])

    def test_requires_apply_for_start(self):
        with self.assertRaises(SystemExit):
            controller.main(["start-worker","--watch"])


if __name__=="__main__":
    unittest.main()
