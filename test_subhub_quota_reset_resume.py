"""Offline regression: quota-reset resume targets only unfinished movie provider checks."""
import json
import sqlite3
import time
import unittest
from unittest.mock import patch

from tools import ja_first_search_pilot as search


def movie(jid):
    return {"jellyfin_id":jid,"kind":"Movie","status":"ready_ja_search",
            "title":"Sample Film","year":2020,
            "host_path":"/mnt/2TB/Plex Expansion/Movies/Drama/Sample Film.mkv"}


class QuotaResetResumeTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE searches (jellyfin_id TEXT PRIMARY KEY,"
                        "outcome TEXT, searched_at INTEGER, results_json TEXT)")
        self.now=int(time.time())
        self.ids=["a"*32,"b"*32,"c"*32,"d"*32,"e"*32,"f"*32]
        entries=[
            ("partial",7200,{"incomplete_providers":["subdl"]}),
            ("review",10800,{"provider_gates":{"opensubtitles":"ok",
                                              "subdl":"cooldown"},
                             "incomplete_providers":["subdl"]}),
            ("plausible",10800,{"provider_gates":{"opensubtitles":"ok",
                                                 "subdl":"ok"},
                                "incomplete_providers":[]}),
            ("partial",300,{"incomplete_providers":["subdl"]}),
            ("deferred",35*86400,{"incomplete_providers":["subdl"]}),
        ]
        for jid,(status,seconds,meta) in zip(self.ids,entries):
            self.db.execute("INSERT INTO searches VALUES (?,?,?,?)",
                            (jid,status,self.now-seconds,json.dumps(meta)))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def pick(self,**kwargs):
        with patch.object(search.movie_scope,"matches",return_value=True), \
             patch.object(search.priorities,"priority",return_value=0), \
             patch.object(search.priorities,"active_coverage_queue",
                          side_effect=AssertionError("owner_resume_not_coverage_queue")), \
             patch.object(search,"query_for",return_value={"title":"Sample Film"}):
            return search.pick([movie(i) for i in self.ids],self.db,100,
                               scope="movies-all",**kwargs)

    def test_owner_resume_selects_only_eligible_incomplete_provider_history(self):
        work=self.pick(resume_incomplete=True)
        self.assertEqual({w["id"] for w in work},set(self.ids[:2]))
        self.assertEqual(len(work),2)

    def test_default_cooldown_still_applies_to_recent_incomplete(self):
        with patch.object(search.movie_scope,"matches",return_value=True), \
             patch.object(search.priorities,"active_coverage_queue",
                          return_value=None), \
             patch.object(search.priorities,"queue_position",return_value=(1,0)), \
             patch.object(search,"query_for",return_value={"title":"Sample Film"}):
            work=search.pick([movie(i) for i in self.ids],self.db,100,
                             scope="movies-all")
        self.assertNotIn(self.ids[0],{w["id"] for w in work})
        self.assertNotIn(self.ids[1],{w["id"] for w in work})

    def test_resume_rejects_unscoped_or_combined_modes(self):
        with self.assertRaisesRegex(ValueError,"resume_incomplete_requires"):
            search.pick([],self.db,20,resume_incomplete=True)
        with self.assertRaisesRegex(ValueError,"resume_incomplete_requires"):
            search.pick([],self.db,20,scope="movies-all",
                        resume_incomplete=True,rescan_missing=True)

    def test_successful_prior_hit_never_requeried_by_resume(self):
        work=self.pick(resume_incomplete=True)
        self.assertNotIn(self.ids[2],{w["id"] for w in work})

    def test_recent_or_stale_incomplete_does_not_requery(self):
        work=self.pick(resume_incomplete=True)
        self.assertNotIn(self.ids[3],{w["id"] for w in work})
        self.assertNotIn(self.ids[4],{w["id"] for w in work})


if __name__=="__main__":
    unittest.main()
