"""Offline tests for live monitor: honest progress, activity and no mutation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import bruiser_live_view as live


class LiveViewTests(unittest.TestCase):
    def test_progress_bars_are_numeric_and_not_faked(self):
        self.assertIn("24 / 600",live.bar(24,600))
        self.assertIn("4%",live.bar(24,600))
        self.assertIn("not yet measurable",live.bar(0,0))

    def test_batch_snapshot_is_explicit_about_real_vs_planned(self):
        fixture={"batch_id":"batch-20261106T031534Z",
                 "state":"running","phase":"search_opensubtitles",
                 "cycle":1,"cycles":5,"phase_current":27,"phase_total":600,
                 "search_budget":600,
                 "last_item":"Example S01E01",
                 "updated_utc":"2026-11-06T03:15:34+00:00",
                 "counts":{"search_started":27,"search_plausible":3,
                           "search_review":22,"search_none":1,"search_errors":0,
                           "staged":2,"published_new":1,"held_titles":4}}
        result=live.terminal_screen(fixture,True,
                 ["[27/600] SEARCHING: Example"],88)
        self.assertIn("SEARCH OPENSUBTITLES",result)
        self.assertIn("27 / 600",result)
        self.assertIn("3,000",result)
        self.assertIn("Newly published: 1",result)
        self.assertIn("Completed: 26",result)
        self.assertIn("In-flight: 1",result)
        self.assertIn("Review needed: 22",result)
        self.assertIn("LIVE BATCH",result)
        self.assertIn("Ctrl+C closes this VIEW, NOT the batch.",result)

    def test_queued_startup_does_not_fabricate_progress(self):
        fixture={"batch_id":"batch-1","state":"running","phase":"queued",
                 "cycle":0,"cycles":5,"search_budget":600,
                 "updated_utc":"2026-11-06T03:15:34+00:00",
                 "phase_current":0,"phase_total":0,"counts":{}}
        result=live.terminal_screen(fixture,True,[],90)
        self.assertIn("STARTUP / PREFLIGHT",result)
        self.assertIn("not yet measurable",result)
        self.assertIn("No subtitle activity can be inferred",result)

    def test_staged_publication_progress_from_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)/"private"
            base.mkdir(mode=0o700)
            path=base/"job.log"
            path.write_text(
                "=== PHASE sync_and_publish 2026-11-06T03:30Z ===\n"
                "=== UNIFIED JAPANESE SUBTITLE PUBLISH QUEUE ===\n"
                "Staged candidates: 26 | unique titles: 21 | max new sidecars: 21\n"
                "MEDIA: aaa | candidate IDs: 123\n"
                "MEDIA: bbb | candidate IDs: 456\n",encoding="utf-8")
            path.chmod(0o600)
            with patch.object(live,"ROOT",base):
                self.assertEqual(
                    live.published_stage_progress(path,"sync_and_publish"),
                    (2,21))
                self.assertEqual(
                    live.published_stage_progress(path,"search_opensubtitles"),
                    None)

    def test_terminal_publisher_title_is_not_stale_staging_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "private"
            base.mkdir(mode=0o700)
            path = base / "job.log"
            logs = (
                "=== PHASE stage_matched_japanese 2026-11-06T04:01Z ===\\n"
                "[12/30] STAGING: Bowfinger (1999)\\n"
                "=== PHASE sync_and_publish 2026-11-06T04:02Z ===\\n"
                "=== UNIFIED JAPANESE SUBTITLE PUBLISH QUEUE ===\\n"
                "Staged candidates: 29 | unique titles: 29 | max new sidecars: 30\\n"
                "MEDIA: one | candidate IDs: 123\\n"
            )
            path.write_text(logs, encoding="utf-8")
            path.chmod(0o600)
            data = {"batch_id": "batch-2", "state": "running",
                    "phase": "sync_and_publish", "cycle": 3, "cycles": 12,
                    "search_budget": 100, "last_item": "Bowfinger (1999)",
                    "log": str(path), "counts": {},
                    "updated_utc": "2026-11-06T04:02:00+00:00"}
            with patch.object(live, "ROOT", base):
                text = live.terminal_screen(data, True, [], 88)
                self.assertIn("Validating subtitle 1 / 29", text)
                self.assertNotIn("Bowfinger", text)
                path.write_text(logs + "RESULT: The Shining (1980) | ready_ffsubsync\\n",
                                encoding="utf-8")
                text = live.terminal_screen(data, True, [], 88)
                self.assertIn("Last evaluated: The Shining (1980)", text)

    def test_recent_log_is_filtered_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)/"private"
            base.mkdir(mode=0o700)
            path=base/"job.log"
            path.write_text(
                "some unrelated trace\n[12/600] SEARCHING: Example\n"
                'BRUISER_PUBLISH_ITEM: {"jellyfin_id":"'+("a"*32)+
                '","result":"held","reason":"timing"}\n',
                encoding="utf-8")
            path.chmod(0o600)
            with patch.object(live,"ROOT",base):
                rows=live.recent_log(path,5)
                self.assertEqual(len(rows),2)
                self.assertIn("Held media",rows[1])
            path.chmod(0o644)
            with patch.object(live,"ROOT",base):
                self.assertEqual(live.recent_log(path,5),[])

    def test_incremental_draw_only_changes_modified_rows(self):
        class Window:
            def __init__(self):
                self.calls = []
                self.erases = 0
            def getmaxyx(self):
                return (25, 88)
            def erase(self):
                self.erases += 1
            def addnstr(self, row, col, text, limit):
                self.calls.append((row, text))
            def noutrefresh(self):
                pass
        window=Window()
        with patch.object(live.curses, "doupdate"):
            snapshot,size=live.draw_changed_lines(window, "TITLE\nSEARCH 9\n", (), None)
            self.assertEqual(window.erases,1)
            self.assertEqual(len(window.calls),2)
            snapshot,size=live.draw_changed_lines(window, "TITLE\nSEARCH 9\n",snapshot,size)
            self.assertEqual(window.erases,1)
            self.assertEqual(len(window.calls),2)
            snapshot,size=live.draw_changed_lines(window, "TITLE\nSEARCH 10\n",snapshot,size)
            self.assertEqual(window.erases,1)
            self.assertEqual(len(window.calls),3)
            self.assertEqual(window.calls[-1][0],1)

    def test_curses_viewer_never_clears_every_refresh(self):
        from inspect import getsource
        self.assertNotIn("\\033[2J",getsource(live.interactive_view))
        self.assertIn("curses.wrapper(",getsource(live.main))
        self.assertIn("curses.doupdate()",getsource(live.draw_changed_lines))

    def test_monitor_is_read_only_and_ctrl_c_is_view_only(self):
        from inspect import getsource
        body=getsource(live.main)
        self.assertNotIn("bruiser-subs stop",body)
        self.assertNotIn("subprocess.Popen",body)
        self.assertIn("except KeyboardInterrupt",body)


if __name__=="__main__":
    unittest.main()
