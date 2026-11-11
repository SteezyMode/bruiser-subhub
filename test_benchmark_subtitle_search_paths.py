"""Offline tests for the capped, non-downloading Jellyfin search comparison."""
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools import benchmark_subtitle_search_paths as benchmark


class JellyfinSubtitleComparison(unittest.TestCase):
    def setUp(self):
        self.movie={"kind":"Movie","title":"Bride of Chucky","year":1998,
                    "jellyfin_id":"a"*32}
        self.ep={"kind":"Episode","title":"Episode","year":2007,
                 "series_title":"It's Always Sunny in Philadelphia",
                 "season":7,"episode":2,"jellyfin_id":"b"*32}
        self.rows=[self.movie,self.ep]

    def test_select_movie_and_episode_by_actual_catalog_identity(self):
        rows=benchmark.select(self.rows,
            ["Bride of Chucky"],["It's Always Sunny in Philadelphia S07E02"])
        self.assertEqual(rows,[self.movie,self.ep])
        for args in (([],[]),(["Missing"],[]),
                     (["Bride of Chucky"]*4,[])):
            with self.assertRaises(ValueError):
                benchmark.select(self.rows,*args)

    def test_ambiguous_movie_does_not_guess(self):
        with self.assertRaisesRegex(ValueError,"ambiguous"):
            benchmark.select([self.movie,self.movie],["Bride of Chucky"],[])

    def test_remote_search_only_sends_authenticated_get_to_jellyfin(self):
        outgoing=[]
        def opener(req,timeout):
            outgoing.append(req)
            self.assertEqual(req.method,"GET")
            self.assertEqual(timeout,100)
            return io.BytesIO(json.dumps([{
                "ProviderName":"OpenSubtitles",
                "Name":"Bride.Of.Chucky.1998.ja",
                "ThreeLetterISOLanguageName":"jpn",
                "IsHashMatch":False
            }]).encode())
        result=benchmark.jellyfin_search(
            self.movie,"SECRET_JELLYFIN_AUTH",opener=opener)
        self.assertEqual(result["remote_count"],1)
        self.assertEqual(len(outgoing),1)
        self.assertTrue(outgoing[0].full_url.endswith(
            "/Items/"+"a"*32+"/RemoteSearch/Subtitles/ja"))
        self.assertEqual(outgoing[0].get_header("Authorization"),
                         "SECRET_JELLYFIN_AUTH")
        self.assertNotIn("SECRET_JELLYFIN_AUTH",json.dumps(result))
        self.assertNotIn("Id",result["examples"][0])

    def test_saved_history_comparison_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"search.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("""CREATE TABLE searches(
                    jellyfin_id TEXT,outcome TEXT,plausible_count INTEGER,
                    results_json TEXT)""")
                db.execute("INSERT INTO searches VALUES(?,?,?,?)",
                    ("a"*32,"none",0,json.dumps({
                        "provider_total":50,
                        "rejected_candidates":[{"filename":"wrong"}],
                        "strategy_version":4})))
            result=benchmark.saved(self.movie,database=path)
            self.assertEqual(result["state"],"none")
            self.assertEqual(result["provider_reported_hits"],50)
            self.assertEqual(result["rejected_saved"],1)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute(
                    "SELECT outcome FROM searches").fetchone()[0],"none")


if __name__=="__main__":
    unittest.main()
