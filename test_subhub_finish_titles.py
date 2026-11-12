"""Offline regression: exact media title tracking, legacy live-job journal."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import subhub_finish_titles as t


class TitleHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.original_root=t.ROOT
        self.original_db=t.DB
        t.ROOT=self.root
        t.DB=self.root/"finish-scope-items.sqlite3"
        self.addCleanup(lambda: setattr(t,"ROOT",self.original_root))
        self.addCleanup(lambda: setattr(t,"DB",self.original_db))
        t._CACHE.update(when=0,key=None,value=None)

    def test_persisted_titles_separate_existing_source_and_plamo(self):
        a,b,c="a"*32,"b"*32,"c"*32
        names={
            a:{"kind":"Movie","title":"Avengers: Age of Ultron","year":2015},
            b:{"kind":"Movie","title":"Crawl","year":2019},
            c:{"kind":"Episode","title":"Episode Three",
               "series_title":"Example Show"}
        }
        t.initialize("1000-222",[(0,0,a),(0,0,b),(3,3,c)],names,{a})
        t.update(b,"published_source","synchronized Japanese source")
        t.update(c,"plamo_queued","all credible JA releases exhausted")
        result=t.persisted("1000-222",state="all")
        self.assertTrue(result["complete_history"])
        self.assertEqual(result["counts"]["covered_initial"],1)
        self.assertEqual(result["counts"]["published_source"],1)
        self.assertEqual(result["counts"]["plamo_queued"],1)
        self.assertEqual(t.persisted("1000-222",state="published")
                         ["items"][0]["title"],"Crawl (2019)")
        self.assertIn("Example Show S03E03",
                      t.persisted("1000-222",state="plamo")["items"][0]["title"])
        self.assertIsNone(t.persisted("9999-222"))
        self.assertEqual(t.persisted("1000-222",state="covered")["total_matching"],2)

    def test_legacy_current_movie_id_resolves_title_not_s00e000(self):
        a,b="a"*32,"b"*32
        receipt={"started_at":1200,"updated_utc":"run-1",
                 "state":"running","phase":"source",
                 "current":"S00E000 "+b}
        logs=[
            "FINISH_PLAMO_QUEUE: "+a+" Japanese sources exhausted",
            "FINISH_SOURCE_RETRY: "+b+" providers_incomplete_or_deferred",
        ]
        with mock.patch.object(t,"_journal",return_value=logs), \
             mock.patch.object(t,"_catalog_titles",
                               return_value={
                                a:("A Nightmare on Elm Street (1984)","Movie"),
                                b:("Barbie (2023)","Movie")}):
            view=t.legacy(receipt)
        self.assertFalse(view["complete_history"])
        states={i["title"]:i["state"] for i in view["items"]}
        self.assertEqual(states["Barbie (2023)"],"source_active")
        self.assertEqual(states["A Nightmare on Elm Street (1984)"],
                         "plamo_queued")
        self.assertEqual(t.legacy(receipt,state="plamo")["total_matching"],1)

    def test_legacy_covered_event_is_not_claimed_newly_published(self):
        jid="a"*32
        receipt={"started_at":1200,"updated_utc":"run-2",
                 "state":"running","phase":"source","current":""}
        with mock.patch.object(t,"_journal",return_value=[
                "FINISH_COVERED: "+jid]), \
             mock.patch.object(t,"_catalog_titles",
                               return_value={jid:("Example (2024)","Movie")}):
            view=t.legacy(receipt)
        self.assertEqual(view["items"][0]["state"],"covered_observed")
        self.assertEqual(t.legacy(receipt,state="published")["total_matching"],0)
        self.assertEqual(t.legacy(receipt,state="covered")["total_matching"],1)


if __name__=="__main__":
    unittest.main()
