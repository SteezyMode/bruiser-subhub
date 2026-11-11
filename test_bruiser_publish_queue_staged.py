"""Staged-subtitle recovery: select pending queue items only; no provider calls."""
import sys
from pathlib import Path
import unittest

TOOLS=str(Path(__file__).resolve().parent/"tools")
sys.path.insert(0,TOOLS)
try:
    import ja_first_publish_queue as pub
finally:
    sys.path.remove(TOOLS)


class StagedRecoveryTests(unittest.TestCase):
    def test_filters_only_pending_already_staged_subtitles(self):
        records=[
            ("a"*32,"1","f"*64),
            ("a"*32,"2","e"*64),
            ("b"*32,"3","d"*64),
            ("c"*32,"4","c"*64),
            ("d"*32,"5","b"*64),
        ]
        queue={
            "a"*32:("align_existing_staged_ja","pending",10,"/video/a.mkv"),
            "b"*32:("align_existing_staged_ja","held",10,"/video/b.mkv"),
            "c"*32:("search_ja","pending",40,"/video/c.mkv"),
        }
        kept=pub.queued_staged_titles(records,queue_reader=lambda:queue)
        self.assertEqual(kept,records[:2])
        self.assertEqual(len(pub.unique_titles(kept,100)),1)

    def test_generic_series_selector_filters_exact_owner_scope(self):
        records=[
            ("a"*32,"1","f"*64),("b"*32,"2","e"*64),
            ("c"*32,"3","d"*64),("d"*32,"4","c"*64),
        ]
        rows=[
            {"kind":"Episode","jellyfin_id":"a"*32,"series_title":"Sunny",
             "season":9,"status":"ready_ja_search"},
            {"kind":"Episode","jellyfin_id":"b"*32,"series_title":"Sunny",
             "season":8,"status":"ready_ja_search"},
            {"kind":"Episode","jellyfin_id":"c"*32,"series_title":"Other",
             "season":9,"status":"ready_ja_search"},
            {"kind":"Episode","jellyfin_id":"d"*32,"series_title":"Sunny",
             "season":9,"status":"existing_japanese_subtitle"},
        ]
        self.assertEqual(pub.select_staged_series(records, rows, "Sunny", 9),
                         records[:1])
        self.assertEqual(pub.select_staged_series(records, rows, "Sunny"),
                         records[:2])
        self.assertEqual(pub.select_staged_series(records, rows, "Other"),
                         records[2:3])

    def test_missing_queue_blocks_explicit_recovery(self):
        with self.assertRaisesRegex(RuntimeError,"queue_not_installed"):
            pub.queued_staged_titles([],queue_reader=lambda:None)

    def test_no_saved_stage_bytes_returns_no_titles(self):
        tasks={"a"*32:("align_existing_staged_ja","pending",10,"/video/a.mkv")}
        self.assertEqual(pub.queued_staged_titles([],queue_reader=lambda:tasks),[])

    def test_existing_integrity_gates_remain_wired(self):
        self.assertTrue(callable(pub.ff.prepare))
        self.assertTrue(callable(pub.direct.publish))
        self.assertTrue(callable(pub.existing_verdict))
        self.assertTrue(callable(pub.mark_completed))


if __name__=="__main__":
    unittest.main()
