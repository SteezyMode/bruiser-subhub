"""Offline end-to-end contracts for partial Japanese provider availability.

Reproduces the actual Nov 11 host failure: SubDL paced, OpenSubtitles open.
No Docker, network access, credentials or subtitle downloads.
"""
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from tools import ja_first_search_pilot as search
from tools import ja_first_source_tracker as tracker
from tools import bruiser_coverage_queue as coverage


def run_worker(job, gates, replies):
    """Feed each GET /health from a scripted sequence, count actual POSTs."""
    post=[]
    states=iter(gates)
    data=iter(replies)
    def urlopen(req, timeout):
        if req.data is None:
            statuses=next(states)
            return io.BytesIO(json.dumps({"providers":[
                {"name":name,"enabled":True,"initialized":True,"gate":state}
                for name,state in statuses.items()
            ]}).encode())
        post.append(json.loads(req.data))
        return io.BytesIO(json.dumps(next(data)).encode())

    cfg=types.ModuleType("config")
    cfg.get_settings=lambda: SimpleNamespace(api_key="TEST_PRIVATE_KEY")
    output=io.StringIO()
    with mock.patch.dict(sys.modules,{"config":cfg}), \
         mock.patch("urllib.request.urlopen",side_effect=urlopen), \
         mock.patch("time.sleep"), \
         mock.patch.object(sys,"stdin",io.StringIO(json.dumps([job]))), \
         mock.patch.object(sys,"stdout",output):
        exec(search.CONTAINER_WORKER,{"__name__":"__main__"})
    return json.loads(output.getvalue()),post


OPEN={"opensubtitles":"ok","subdl":"budget_exhausted"}
CLOSED={"opensubtitles":"budget_exhausted","subdl":"budget_exhausted"}
BOTH={"opensubtitles":"ok","subdl":"ok"}


class PartialProviderTests(unittest.TestCase):
    def test_one_provider_paced_other_can_still_search(self):
        reply,posts=run_worker(
            {"id":"film","query":{"title":"Mad God","year":2021,"language":"ja"}},
            [OPEN,OPEN], [{"total":0,"results":[]}])
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["partial"])
        self.assertFalse(reply.get("deferred",False))
        self.assertEqual(reply["incomplete_providers"],["subdl"])
        self.assertEqual(reply["requests_made"],1)
        self.assertEqual(len(posts),1)
        self.assertEqual(posts[0]["title"],"Mad God 2021")

    def test_only_when_all_enabled_sources_blocked_no_post(self):
        reply,posts=run_worker(
            {"id":"episode","query":{
                "series_title":"Example","season":2,"episode":3,"language":"ja"}},
            [CLOSED],[])
        self.assertTrue(reply["deferred"])
        self.assertEqual(posts,[])
        self.assertEqual(reply["requests_made"],0)

    def test_partial_prior_result_preserved_if_last_provider_closes(self):
        rejected={"provider":"opensubtitles","subtitle_id":"144",
                  "filename":"Bride.of.Re-Animator.1990.ja",
                  "language":"ja","matches":[]}
        reply,posts=run_worker(
            {"id":"bride","query":{
                "title":"Bride of Chucky","year":1998,"language":"ja",
                "imdb_id":"tt0144120"}},
            [BOTH,CLOSED,CLOSED],
            [{"total":1,"results":[rejected]}])
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["partial"])
        self.assertFalse(reply["deferred"])
        self.assertEqual(reply["requests_made"],1)
        self.assertEqual(reply["results"][0]["subtitle_id"],"144")
        self.assertEqual(len(posts),1)
        self.assertEqual(reply["incomplete_providers"],
                         ["opensubtitles","subdl"])

    def test_partial_search_is_not_none_and_retries_after_window(self):
        row={"jellyfin_id":"test","kind":"Movie","title":"Mad God",
             "year":2021,"status":"ready_ja_search",
             "host_path":"/mnt/2TB/Movies/Mad.God.mkv"}
        job={"id":"test","row":row}
        with tempfile.TemporaryDirectory() as temp:
            db_path=Path(temp)/"source.sqlite3"
            with mock.patch.object(search,"DB",db_path):
                with search.open_db() as db:
                    search.save_attempt(db,job,"partial",0,[],
                        strategy_version=4,query_variant="movie_title_year",
                        provider_gates=OPEN,incomplete_providers=["subdl"])
                    outcome,body=db.execute(
                        "SELECT outcome,results_json FROM searches"
                    ).fetchone()
                    self.assertEqual(outcome,"partial")
                    self.assertEqual(json.loads(body)["incomplete_providers"],["subdl"])
                    plan=coverage.japanese_source_plan(row,
                        {"test":("partial",0,0)},set())
                    self.assertEqual(plan[0],"search_ja")
                    self.assertIn("incomplete",plan[1])
                    rank={"test":("search_ja","pending",40,row["host_path"])}
                    with mock.patch.object(search.priorities,"active_coverage_queue",
                                           return_value=rank), \
                         mock.patch.object(search,"query_for",
                                           return_value={"title":"Mad God"}):
                        self.assertEqual(search.pick([row],db,1),[])
                        db.execute(
                            "UPDATE searches SET searched_at=searched_at-22*3600")
                        self.assertEqual(
                            [x["id"] for x in search.pick([row],db,1)],["test"])

    def test_tracker_uses_partial_not_false_none(self):
        events=[
            (1,"RUNNING_SOURCES_ONLY_CYCLE search_budget=3 stage_budget=1 publish_limit=1"),
            (2,"=== DISCOVERY ==="),
            (3,"Search requests planned: 3 | budget: 3"),
            (4,"[1/3] PARTIAL: plausible=0 review=0 provider_total=0 incomplete=subdl"),
            (5,"[2/3] PLAUSIBLE: plausible=1 review=0 provider_total=1"),
            (6,"[3/3] DEFERRED: {'opensubtitles': 'budget_exhausted'}"),
            (7,"AUTOFILL_CYCLE_COMPLETE"),
        ]
        state=tracker.parse(events)
        self.assertEqual(state["search_completed"],2)
        self.assertEqual(state["search_partial"],1)
        self.assertEqual(state["search_none"],0)
        self.assertEqual(state["search_found"],1)
        self.assertEqual(state["search_deferred"],1)
        self.assertTrue(state["search_stopped_early"])


if __name__=="__main__":
    unittest.main()
