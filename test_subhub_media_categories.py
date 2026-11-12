"""Offline checks for genre browsing and the movie-only full source scope."""
import unittest
from unittest.mock import patch
from pathlib import Path
import sqlite3
import tempfile
import time
from tools import subhub_media_categories as categories
from tools import ja_first_movie_scope as scope
from tools import ja_first_search_pilot as search
from tools import ja_first_catalog_manifest as intake


class UnifiedCategories(unittest.TestCase):
    def test_one_action_category_for_both_drives(self):
        a=categories.categories("Movie",
            "/mnt/2TB/Plex Expansion/Movies/Action/FilmA.mkv",["Action"])
        b=categories.categories("Movie",
            "/mnt/BigDisk/Video/Movies/ACTION/FilmB.mkv",["Action"])
        self.assertEqual([x.casefold() for x in a],["action"])
        self.assertEqual([x.casefold() for x in b],["action"])

    def test_tv_documentary_comes_from_genre_or_existing_folder(self):
        self.assertEqual(categories.categories("Episode",
            "/mnt/2TB/Television/Documentaries/Nature/S01E01.mkv",[]),
            ["Documentary"])
        self.assertEqual(categories.categories("Episode",
            "/mnt/BigDisk/Television/Episodic/Nature/S01E01.mkv",
            ["Documentaries"]),["Documentary"])

    def test_horror_and_drama_full_pass_is_movies_only_across_both_drives(self):
        films=[
            {"kind":"Movie","host_path":
             "/mnt/2TB/Plex Expansion/Movies/Horror/FilmA.mkv","genres":[]},
            {"kind":"Movie","host_path":
             "/mnt/BigDisk/Video/Movies/Action/FilmB.mkv",
             "genres":["Drama","Action"]},
            {"kind":"Movie","host_path":
             "/mnt/BigDisk/Video/Movies/Drama/FilmC.mkv","genres":[]},
        ]
        self.assertTrue(all(scope.matches(x,"horror-drama-folders") for x in films))
        self.assertFalse(scope.matches({
            "kind":"Movie","host_path":
            "/mnt/2TB/Plex Expansion/Movies/Action/FilmD.mkv",
            "genres":["Action"]},"horror-drama-folders"))
        self.assertFalse(scope.matches({
            "kind":"Episode","host_path":
            "/mnt/2TB/Television/Horror/Show/S01E01.mkv",
            "genres":["Horror"]},"horror-drama-folders"))

    def test_deferred_subtitle_search_is_not_repeated_during_quota_window(self):
        now=int(time.time())
        rows=[{"kind":"Movie","jellyfin_id":"a"*32,"title":"Film",
               "year":2020,"status":"ready_ja_search",
               "host_path":"/mnt/2TB/Plex Expansion/Movies/Horror/Film.mkv",
               "genres":["Horror"]}]
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE searches (jellyfin_id TEXT, outcome TEXT, "
                       "searched_at INTEGER, results_json TEXT)")
            db.execute("INSERT INTO searches VALUES (?,?,?,?)",
                       ("a"*32,"deferred",now-60,"{}"))
            with patch.object(search.priorities,"active_coverage_queue",
                              return_value=None), \
                 patch.object(search.priorities,"queue_position",
                              return_value=(0,0)), \
                 patch.object(search,"query_for",return_value={"title":"Film"}):
                self.assertEqual(search.pick(rows,db,10,"horror-drama-folders"),[])
                db.execute("UPDATE searches SET searched_at=?",
                           (now-21*3600,))
                self.assertEqual(len(search.pick(rows,db,10,"horror-drama-folders")),1)

    def test_episodes_inherit_documentary_from_real_jellyfin_series(self):
        with tempfile.TemporaryDirectory() as temp:
            video=Path(temp)/"S01E01.mkv"
            video.write_bytes(b"offline test")
            ident="a"*32
            raw={"Type":"Episode","Id":"b"*32,
                 "Name":"Episode 1","Path":str(video),
                 "SeriesId":ident,"SeriesName":"Nature Docs",
                 "ParentIndexNumber":1,"IndexNumber":1,
                 "Genres":[]}
            series={ident:{"Id":ident,"Name":"Nature Docs",
                           "Genres":["Documentary"]}}
            with patch.object(intake,"stream_state",
                              return_value=("known","eng",False)), \
                 patch.object(intake,"sidecar_ja",return_value=False):
                result=intake.classify(raw,series,
                   [(Path(temp),Path("/media/test"))],{})
            self.assertEqual(result["status"],"ready_ja_search")
            self.assertEqual(result["genres"],["Documentary"])

    def test_adding_documentary_does_not_automatically_pick_tv(self):
        movie=categories.categories("Movie",
            "/mnt/BigDisk/Video/Movies/Horror/Nature.mkv",
            ["Documentary"])
        self.assertIn("Documentary",movie)
        tv=categories.categories("Episode",
            "/mnt/BigDisk/Television/Episodic/Docs/S01E01.mkv",[])
        self.assertEqual(tv,["Other Television"])


if __name__=="__main__":
    unittest.main()
