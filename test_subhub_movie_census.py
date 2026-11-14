"""Movie-wide report and resumable discovery, without provider or media writes."""
import json
import sqlite3
import time
import unittest
from unittest.mock import patch

from tools import subhub_movie_census as census
from tools import ja_first_search_pilot as search


def movie(jid,title,status="ready_ja_search"):
    return {
        "kind":"Movie","title":title,"year":2020,
        "jellyfin_id":jid,"status":status,
        "host_path":"/mnt/2TB/Plex Expansion/Movies/Drama/"+title+".mkv",
    }


def search_record(status,now,*,age=1000,candidates=(),gates=None,incomplete=()):
    doc={
        "candidates":list(candidates),
        "provider_gates":({"opensubtitles":"ok","subdl":"ok"}
                          if gates is None else gates),
        "incomplete_providers":list(incomplete),
        "strategy_version":5,
    }
    return status,int(now-age),json.dumps(doc)


class MovieCensusTests(unittest.TestCase):
    def setUp(self):
        self.now=int(time.time())
        self.ids=[chr(97+i)*32 for i in range(9)]
        self.rows=[
            movie(self.ids[0],"Covered","existing_japanese_subtitle"),
            movie(self.ids[1],"No Search"),
            movie(self.ids[2],"No Saved Candidates"),
            movie(self.ids[3],"Partial Candidate"),
            movie(self.ids[4],"Saved JA Candidate"),
            movie(self.ids[5],"Staged JA Candidate"),
            movie(self.ids[6],"Japanese Audio","japanese_audio"),
            movie(self.ids[7],"Unverified Media","review_host_file_missing"),
            movie(self.ids[8],"Old Failed Search"),
        ]
        plausible={"grade":"plausible","provider":"subdl",
                   "subtitle_id":"1-1234"}
        review={"grade":"review","provider":"opensubtitles",
                "subtitle_id":"1234"}
        self.searches={
            self.ids[2]:search_record("none",self.now),
            self.ids[3]:search_record("review",self.now,
                          candidates=[review],
                          gates={"opensubtitles":"ok","subdl":"cooldown"},
                          incomplete=["subdl"]),
            self.ids[4]:search_record("review",self.now,
                                      candidates=[review]),
            self.ids[5]:search_record("plausible",self.now,
                                      candidates=[plausible]),
            self.ids[8]:search_record("error",self.now,age=86400*3),
        }
        self.staged={self.ids[5]:2}
        self.outcomes={self.ids[5]:("held","RuntimeError: sync_not_verified")}

    def test_all_movies_count_once_and_holds_are_separate(self):
        summary,rows=census.classify(
            self.rows,self.searches,self.staged,self.outcomes,
            now=self.now,sidecar_check=lambda *_:False)
        self.assertEqual(summary["movies"],9)
        self.assertEqual(summary["subtitle_coverage"]["present"],1)
        self.assertEqual(summary["subtitle_coverage"]["missing"],7)
        self.assertEqual(summary["subtitle_coverage"]["unverified"],1)
        counts=summary["mutually_exclusive_source_buckets"]
        self.assertEqual(counts["has_japanese_subtitle"],1)
        self.assertEqual(counts["not_searched"],1)
        self.assertEqual(counts["searched_no_saved_candidate"],1)
        self.assertEqual(counts["saved_candidates_not_staged"],2)
        self.assertEqual(counts["staged_not_published"],1)
        self.assertEqual(counts["japanese_audio_no_subtitle"],1)
        self.assertEqual(counts["inventory_needs_verification"],1)
        self.assertEqual(counts["search_needs_completion"],1)
        self.assertEqual(sum(counts.values()),9)
        self.assertEqual(summary["last_publisher_hold_receipts_among_missing"],
                         {"held":1})
        self.assertEqual(summary["movies_with_saved_candidates"],3)
        self.assertEqual(summary["saved_candidate_releases"],3)
        self.assertEqual(summary["review_grade_releases"],2)

    def test_provider_evidence_is_separate_from_saved_candidates(self):
        state,doc,_=census.search_evidence(self.searches[self.ids[3]],now=self.now)
        self.assertEqual(state,"provider_incomplete")
        self.assertEqual(len(doc["candidates"]),1)
        self.assertEqual(census.search_evidence(
            self.searches[self.ids[4]],now=self.now)[0],"core_gates_ok")
        self.assertEqual(census.search_evidence(None,now=self.now)[0],
                         "not_searched")

    def test_missing_core_gate_or_stale_search_not_called_complete(self):
        unknown=search_record("none",self.now,gates={"opensubtitles":"ok"})
        self.assertEqual(census.search_evidence(unknown,now=self.now)[0],
                         "provider_evidence_unverified")
        old=search_record("none",self.now,age=31*86400)
        self.assertEqual(census.search_evidence(old,now=self.now)[0],
                         "search_stale_30d")

    def test_out_of_scope_movie_and_episode_are_not_in_movie_total(self):
        tv=dict(self.rows[0],kind="Episode",jellyfin_id="z"*32)
        other=dict(self.rows[0],jellyfin_id="f"*32,
                   host_path="/mnt/1TBNVME/Outside.2020.mkv")
        summary,rows=census.classify(
            self.rows+[tv,other],self.searches,self.staged,self.outcomes,
            now=self.now,sidecar_check=lambda *_:False)
        self.assertEqual(summary["movies"],9)
        self.assertEqual(summary["movie_entries_outside_known_roots"],1)
        self.assertEqual(len(rows),9)

    def test_covered_film_not_mislabeled_hold_even_with_old_receipt(self):
        outcomes=dict(self.outcomes)
        outcomes[self.ids[0]]=("held_unchanged","old failure")
        summary,_=census.classify(self.rows,self.searches,self.staged,outcomes,
                                   now=self.now,sidecar_check=lambda *_:False)
        self.assertEqual(summary["last_publisher_hold_receipts_among_missing"],
                         {"held":1})


class CensusSearchSelectionTests(unittest.TestCase):
    def setUp(self):
        self.now=int(time.time())
        self.ids=[chr(97+i)*32 for i in range(6)]
        self.rows=[movie(i,"Movie "+str(n))
                   for n,i in enumerate(self.ids)]
        self.db=sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE searches (jellyfin_id TEXT PRIMARY KEY,"
                        "outcome TEXT,searched_at INTEGER,results_json TEXT)")
        entries=[
            search_record("plausible",self.now,age=3*86400,
                          candidates=[{"grade":"review","provider":"subdl"}]),
            search_record("review",self.now,age=3*86400,
                          gates={"opensubtitles":"ok","subdl":"cooldown"},
                          incomplete=["subdl"]),
            search_record("partial",self.now,age=300,
                          gates={"opensubtitles":"ok","subdl":"cooldown"},
                          incomplete=["subdl"]),
            search_record("none",self.now,age=40*86400),
            search_record("error",self.now,age=3*86400),
        ]
        for jid,(status,when,body) in zip(self.ids,entries):
            self.db.execute("INSERT INTO searches VALUES (?,?,?,?)",
                            (jid,status,when,body))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_census_targets_unsurveyed_incomplete_stale_and_failed_only(self):
        with patch.object(search.priorities,"priority",return_value=0), \
             patch.object(search,"query_for",return_value={"title":"Movie"}) as q, \
             patch.object(search.priorities,"active_coverage_queue",
                          side_effect=AssertionError("should_ignore_queue")):
            jobs=search.pick(self.rows,self.db,600,scope="movies-all",
                             coverage_census=True)
        ids={j["id"] for j in jobs}
        self.assertEqual(ids,{self.ids[1],self.ids[3],
                              self.ids[4],self.ids[5]})
        self.assertNotIn(self.ids[0],ids)
        self.assertNotIn(self.ids[2],ids)
        self.assertEqual(q.call_count,4)

    def test_movie_only_flag_cannot_override_existing_search_modes(self):
        with self.assertRaisesRegex(ValueError,"coverage_census_requires"):
            search.pick([],self.db,10,coverage_census=True)
        with self.assertRaisesRegex(ValueError,"coverage_census_requires"):
            search.pick([],self.db,10,scope="movies-all",
                        coverage_census=True,rescan_missing=True)

    def test_missing_imdb_movie_can_be_queried_in_census_but_not_daily(self):
        row=movie(self.ids[5],"No IMDb","review_no_movie_imdb")
        with patch.object(search.Path,"is_file",return_value=True), \
             patch.object(search.Path,"is_symlink",return_value=False), \
             patch.object(search,"sidecar_present",return_value=False):
            self.assertIsNone(search.query_for(row))
            result=search.query_for(row,coverage_census=True)
            self.assertEqual(result["title"],"No IMDb")
            self.assertEqual(result["year"],2020)


if __name__=="__main__":
    unittest.main()
