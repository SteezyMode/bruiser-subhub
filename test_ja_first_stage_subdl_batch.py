"""Offline regression tests for the general SubDL staging handoff."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import ja_first_stage_subdl_batch as batch
from tools import ja_first_cycle as cycle
from tools import install_global_ja_sourcing as installer


def row(jid,title):
    return {"jellyfin_id":jid,"kind":"Movie","status":"ready_ja_search",
            "title":title,"year":2000,"host_path":"/not-present/film.mkv"}


def candidate(sid,provider="subdl",score=80):
    return {"provider":provider,"subtitle_id":sid,"language":"ja",
            "filename":"Movie.2000.Japanese.srt","score":score}


class SubdlBatchTests(unittest.TestCase):
    def test_new_batch_is_installed_and_cycle_requires_it(self):
        self.assertIn("ja_first_stage_subdl_batch.py",installer.SOURCE_FILES)
        self.assertIn("ja_first_stage_subdl_batch.py",installer.NEW_SOURCE_FILES)
        self.assertIn("ja_first_stage_subdl_batch.py",cycle.FILES)
        self.assertIn("ja_first_stage_subdl.py",cycle.FILES)
        self.assertIn("subhub_download_ledger.py",cycle.FILES)

    def test_one_saved_subdl_per_title_and_skip_earlier_staged_id(self):
        first="a"*32
        second="b"*32
        inventory={first:row(first,"First"),second:row(second,"Second")}
        a=candidate("source-one")
        b=candidate("source-two",score=70)
        c=candidate("source-three")
        searches=[
            (first,json.dumps({"candidates":[a,b,candidate("unwanted",provider="opensubtitles")]})),
            (second,json.dumps({"candidates":[c]}))
        ]
        staged_id,_=batch.subdl.numeric_id("source-one")
        with patch.object(batch.stage.priorities,"active_coverage_queue",return_value=None), \
             patch.object(batch.stage.priorities,"queue_position",return_value=(0,0)), \
             patch.object(batch.stage.movie_scope,"matches",return_value=True), \
             patch.object(batch.stage,"rejected_duration_candidates",return_value=set()), \
             patch.object(batch.stage,"alternate_ready",return_value=True), \
             patch.object(batch.subdl,"identity_ok",side_effect=lambda row,c:c["provider"]=="subdl"), \
             patch.object(batch.stage.candidate_progress,"release_match",return_value=1):
            selected=batch.select(inventory,searches,{(first,staged_id)},10)
        self.assertEqual(len(selected),2)
        self.assertEqual(selected[0][1]["subtitle_id"],"source-two")
        self.assertEqual(selected[1][1]["subtitle_id"],"source-three")

    def test_explicit_scope_and_queue_priority_are_respected(self):
        a="a"*32
        b="b"*32
        inventory={a:row(a,"Earlier"),b:row(b,"Later")}
        searches=[(jid,json.dumps({"candidates":[candidate("source-"+jid[0])]}))
                  for jid in (a,b)]
        with patch.object(batch.stage.priorities,"active_coverage_queue",return_value=None), \
             patch.object(batch.stage.priorities,"queue_position",
                          side_effect=lambda r,*args:(0,0) if r["jellyfin_id"]==b else (10,0)), \
             patch.object(batch.stage.movie_scope,"matches",return_value=True), \
             patch.object(batch.stage,"rejected_duration_candidates",return_value=set()), \
             patch.object(batch.stage,"alternate_ready",return_value=True), \
             patch.object(batch.subdl,"identity_ok",return_value=True), \
             patch.object(batch.stage.candidate_progress,"release_match",return_value=1):
            selected=batch.select(inventory,searches,set(),1)
        self.assertEqual(selected[0][0]["jellyfin_id"],b)

    def test_readonly_has_no_acquisition(self):
        with patch.object(batch.stage,"read_inventory",return_value={}), \
             patch.object(batch.stage,"read_saved_searches",return_value=[]), \
             patch.object(batch.stage,"read_staged",return_value=set()), \
             patch.object(batch,"select",return_value=[]), \
             patch.object(batch.subdl,"stage_one") as acquire:
            self.assertEqual(batch.run(budget=2,apply=False),{})
        acquire.assert_not_called()

    def test_subdl_quota_holds_provider_without_touching_other_candidates(self):
        selected=[(row("a"*32,"First"),candidate("one")),
                  (row("b"*32,"Second"),candidate("two"))]
        quota=HTTPError("https://dl.subdl.com",429,"quota",None,None)
        with patch.object(batch.stage,"read_inventory",return_value={}), \
             patch.object(batch.stage,"read_saved_searches",return_value=[]), \
             patch.object(batch.stage,"read_staged",return_value=set()), \
             patch.object(batch,"select",return_value=selected), \
             patch.object(batch.stage,"duration_if_safe",return_value=1000.0), \
             patch.object(batch.subdl,"stage_one",side_effect=quota) as acquire:
            result=batch.run(budget=2,apply=True)
        self.assertEqual(result,{"provider_limited":1})
        self.assertEqual(acquire.call_count,1)

    def test_invalid_cached_zip_is_held_but_does_not_stop_next_title(self):
        selected=[(row("a"*32,"First"),candidate("one")),
                  (row("b"*32,"Second"),candidate("two"))]
        with patch.object(batch.stage,"read_inventory",return_value={}), \
             patch.object(batch.stage,"read_saved_searches",return_value=[]), \
             patch.object(batch.stage,"read_staged",return_value=set()), \
             patch.object(batch,"select",return_value=selected), \
             patch.object(batch.stage,"duration_if_safe",return_value=1000.0), \
             patch.object(batch.subdl,"stage_one",
                          side_effect=[RuntimeError("subdl_archive_srt_rejected:bad_clock"),None]) as acquire:
            result=batch.run(budget=2,apply=True)
        self.assertEqual(result,{"held":1,"staged_or_cached":1})
        self.assertEqual(acquire.call_count,2)

    def test_source_cycle_passes_only_remaining_combined_budget_to_subdl(self):
        calls=[]
        with patch.object(cycle,"required_code"), \
             patch.object(cycle,"native_download_attempts",side_effect=[300,306]), \
             patch.object(cycle,"run_step",side_effect=lambda _,name,file,args:calls.append((name,file,args))), \
             patch.object(cycle,"status"):
            cycle.cycle(Path("/unused"),search_budget=6,stage_budget=10,
                        publish_limit=5,fallback_budget=1,
                        sources_only=True,scope="all")
        self.assertEqual([x[1] for x in calls],[
            "ja_first_search_pilot.py","ja_first_stage_saved_batch.py",
            "ja_first_stage_subdl_batch.py","ja_first_publish_queue.py"])
        self.assertEqual(calls[2][2][1],"4")
        self.assertEqual(calls[3][2][1],"5")

    def test_subdl_skips_when_combined_budget_consumed(self):
        calls=[]
        with patch.object(cycle,"required_code"), \
             patch.object(cycle,"native_download_attempts",side_effect=[120,130]), \
             patch.object(cycle,"run_step",side_effect=lambda _,name,file,args:calls.append(file)), \
             patch.object(cycle,"status"):
            cycle.cycle(Path("/unused"),search_budget=3,stage_budget=10,
                        publish_limit=2,fallback_budget=1,sources_only=True)
        self.assertNotIn("ja_first_stage_subdl_batch.py",calls)


if __name__=="__main__":
    unittest.main()
