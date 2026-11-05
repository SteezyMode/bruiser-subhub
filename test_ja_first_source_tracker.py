"""Read-only Japanese source autofill terminal progress dashboard tests."""
import json
import unittest
from tools import ja_first_source_tracker as monitor


def e(second, message):
    return (float(second), message)


class SourceTrackerTests(unittest.TestCase):
    def test_live_search_and_stage_progress(self):
        events=[
            e(100,"RUNNING_SOURCES_ONLY_CYCLE search_budget=600 stage_budget=200 publish_limit=200"),
            e(101,"=== DISCOVERY ==="),
            e(102,"Search requests planned: 600 | budget: 600"),
            e(103,"[1/600] SEARCHING: Baskin (2015)"),
            e(104,"[1/600] PLAUSIBLE: plausible=1 review=0"),
            e(105,"[2/600] SEARCHING: Together (2025)"),
        ]
        d=monitor.parse(events)
        self.assertEqual(d["search_completed"],1)
        self.assertEqual(d["search_planned"],600)
        self.assertEqual(d["search_found"],1)
        self.assertEqual(d["current"],"Together (2025)")
        self.assertEqual(d["phase"],"Searching Japanese subtitle providers")
        output=monitor.render(d,now=125)
        self.assertIn("1/600",output)
        self.assertIn("25s",output)
        self.assertIn("Current: Together",output)

    def test_second_run_does_not_merge_old_counts(self):
        events=[
            e(10,"RUNNING_SOURCES_ONLY_CYCLE search_budget=8 stage_budget=2 publish_limit=3"),
            e(11,"PUBLISHED: /media/old.ja.srt"),
            e(12,"AUTOFILL_CYCLE_COMPLETE"),
            e(200,"RUNNING_SOURCES_ONLY_CYCLE search_budget=600 stage_budget=200 publish_limit=200"),
            e(201,"=== DISCOVERY ==="),
            e(202,"Search requests planned: 600 | budget: 600"),
            e(203,"[1/600] NONE: plausible=0 review=0"),
        ]
        d=monitor.parse(events)
        self.assertEqual(d["published"],0)
        self.assertEqual(d["search_completed"],1)
        self.assertEqual(d["search_none"],1)
        self.assertFalse(d["complete"])
        self.assertEqual(d["started"],200)

    def test_stage_and_publication_and_hold_events(self):
        events=[
            e(100,"RUNNING_SOURCES_ONLY_CYCLE search_budget=600 stage_budget=200 publish_limit=200"),
            e(101,"=== STAGE CANDIDATES ==="),
            e(102,"Selected: 2 | budget: 200"),
            e(103,"[1/2] STAGING: The X-Files S01E01"),
            e(104,"STAGED: /private/file.ja.srt"),
            e(105,"[2/2] STAGING: Other"),
            e(106,"HELD: Other RuntimeError invalid_release"),
            e(107,"=== PUBLISH VERIFIED JA ==="),
            e(108,"Staged candidates: 3 | unique titles: 3 | max new sidecars: 200"),
            e(109,"MEDIA: abc | candidate IDs: 123"),
            e(110,"RESULT: Fargo (1996) | published_ffsubsync"),
            e(111,"MEDIA: def | candidate IDs: 456"),
            e(112,"RESULT: Twin Peaks S02E13 | ready_ffsubsync"),
            e(113,"PUBLISHED: /private/Twin Peaks.ja.srt"),
            e(114,"MEDIA: ghi | candidate IDs: 789"),
            e(115,"HELD: ghi RuntimeError wrong_language"),
            e(116,"QUEUE SUMMARY: ..."),
            e(117,"AUTOFILL_CYCLE_COMPLETE"),
        ]
        d=monitor.parse(events)
        self.assertEqual(d["stage_attempts"],2)
        self.assertEqual(d["staged"],1)
        self.assertEqual(d["stage_holds"],1)
        self.assertEqual(d["publish_title_checked"],3)
        self.assertEqual(d["published"],1)
        self.assertEqual(d["publish_holds"],1)
        self.assertEqual(d["existing_recognized"],1)
        self.assertEqual(d["phase"],"Completed (source-only)")
        self.assertTrue(d["complete"])
        self.assertEqual(d["current"],"")
        self.assertIn("Newly published: 1",monitor.render(d,now=140))

    def test_endpoints_read_only_and_missing_journal(self):
        self.assertFalse(monitor.parse([])["has_run"])
        self.assertEqual(monitor.bar(1,0),"["+"·"*30+"] pending")
        self.assertEqual(monitor.parse_unit_state("ActiveState=active\nSubState=running\n"),
                         ("active","running"))
        good=json.dumps({"MESSAGE":"[1/4] SEARCHING: Movie",
                         "__REALTIME_TIMESTAMP":"1000000"})
        self.assertEqual(monitor.events_from_jsonl(good+"\nnot JSON\n")[0],
                         (1.0,"[1/4] SEARCHING: Movie"))

    def test_error_never_confused_with_success(self):
        events=[
            e(100,"RUNNING_SOURCES_ONLY_CYCLE search_budget=600 stage_budget=200 publish_limit=200"),
            e(101,"=== DISCOVERY ==="),
            e(102,"JA_SOURCE_AUTOFILL_HELD RuntimeError timeout"),
        ]
        d=monitor.parse(events)
        self.assertTrue(d["failed"])
        self.assertFalse(d["complete"])
        self.assertIn("WARNING:",monitor.render(d,now=130))

    def test_direct_self_test(self):
        monitor.self_test()


if __name__=="__main__":
    unittest.main()
