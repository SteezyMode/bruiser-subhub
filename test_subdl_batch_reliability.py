"""SubDL: candidate failure is not a title hold; fallback candidates remain eligible."""
from collections import Counter
import json
import unittest
from unittest.mock import patch

from tools import ja_first_stage_subdl_batch as batch


def movie():
    return {
        "jellyfin_id":"a"*32,"kind":"Movie","title":"Sample Horror","year":2025,
        "host_path":"/mnt/2TB/Plex Expansion/Movies/Horror/Sample.Horror.mkv",
        "status":"ready_ja_search","genres":["Horror"],
    }


def release(sid):
    return {"provider":"subdl","language":"ja",
            "subtitle_id":sid,"filename":"Sample.Horror.2025.ja.srt",
            "score":80}


class BatchReliabilityTests(unittest.TestCase):
    def _select(self,*,try_alternates, rejected=()):
        row=movie()
        doc={"candidates":[release("abc"),release("def"),release("ghi"),
                           release("jkl")]}
        skipped=Counter()
        with patch.object(batch.stage.priorities,"active_coverage_queue",
                          return_value=None), \
             patch.object(batch.stage,"rejected_duration_candidates",
                          return_value=set()), \
             patch.object(batch.stage,"alternate_ready",return_value=True), \
             patch.object(batch.subdl,"identity_ok",return_value=True), \
             patch.object(batch.subdl,"known_rejected_cached",
                          side_effect=lambda r,c:c["subtitle_id"] in rejected), \
             patch.object(batch.subdl,"numeric_id",
                          side_effect=lambda sid:(sid,"sha")):
            selected=batch.select(
                {row["jellyfin_id"]:row},
                [(row["jellyfin_id"],json.dumps(doc))],
                set(),20,"horror-drama-folders",skipped,
                try_alternates=try_alternates)
        return selected,skipped

    def test_default_selection_retains_one_per_title(self):
        chosen,_=self._select(try_alternates=False)
        self.assertEqual(len(chosen),1)

    def test_wide_apply_tries_three_new_releases_for_same_title(self):
        chosen,_=self._select(try_alternates=True)
        self.assertEqual(len(chosen),3)
        self.assertEqual(len({r["jellyfin_id"] for r,c in chosen}),1)

    def test_remembered_bad_zip_skipped_without_losing_alternative(self):
        chosen,skipped=self._select(try_alternates=True,rejected={"abc"})
        self.assertEqual(skipped["unchanged_bad_cached_zip"],1)
        self.assertEqual({c["subtitle_id"] for r,c in chosen},
                         {"def","ghi","jkl"})

    def test_cause_groups_not_one_undifferentiated_hold(self):
        self.assertEqual(batch.hold_code(
            RuntimeError("subdl_archive_srt_rejected:unparseable_srt_timestamp")),
            "subdl_archive_srt_rejected:unparseable_srt_timestamp")
        self.assertEqual(batch.hold_code(
            RuntimeError("ffprobe_failed")), "ffprobe_failed")


if __name__=="__main__":
    unittest.main()
