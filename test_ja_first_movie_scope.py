"""Offline safeguards for scoped Japanese sourcing across both real movie roots."""
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from tools import ja_first_movie_scope as scope
from tools import ja_first_search_pilot as search
from tools import ja_first_stage_saved_batch as stage


def media(root,folder,name="Example.1989.mkv",jid=None):
    return {
        "kind":"Movie", "jellyfin_id":jid or ("a"*32),
        "host_path":str(root/folder/name),
        "status":"ready_ja_search", "title":"Example","year":1989,
    }


class MovieScopeTests(unittest.TestCase):
    def setUp(self):
        self.two=Path("/mnt/2TB/Plex Expansion/Movies")
        self.four=Path("/mnt/BigDisk/Video/Movies")
        self.horror=media(self.two,"Horror",jid="a"*32)
        self.drama=media(self.four,"Drama, Suspense",jid="b"*32)
        self.outside=media(self.two,"Comedy",jid="c"*32)
        self.title_only=media(self.four,"Comedy",name="Horror.Stories.1999.mkv",jid="d"*32)
        self.tv={"kind":"Episode","jellyfin_id":"e"*32,
                 "host_path":"/mnt/2TB/Plex Expansion/Television/Horror/Example.mkv",
                 "status":"ready_ja_search"}

    def test_includes_both_drives_and_only_selected_folders(self):
        self.assertTrue(scope.matches(self.horror,scope.SCOPE))
        self.assertTrue(scope.matches(self.drama,scope.SCOPE))
        self.assertFalse(scope.matches(self.outside,scope.SCOPE))
        self.assertFalse(scope.matches(self.title_only,scope.SCOPE))
        self.assertFalse(scope.matches(self.tv,scope.SCOPE))
        self.assertFalse(scope.matches(media(self.two,"Other/Horror"),scope.SCOPE))

    def test_all_movies_without_anime_never_includes_tv_or_anime_section(self):
        non_anime=scope.MOVIES_NO_ANIME
        self.assertTrue(scope.matches(self.horror,non_anime))
        self.assertTrue(scope.matches(self.drama,non_anime))
        self.assertTrue(scope.matches(self.outside,non_anime))
        self.assertTrue(scope.matches(self.title_only,non_anime))
        self.assertFalse(scope.matches(self.tv,non_anime))
        anime=media(self.two,"Anime",jid="f"*32)
        self.assertFalse(scope.matches(anime,non_anime))
        anime_folder=media(self.four,"Animation, Anime/Films",jid="1"*32)
        self.assertFalse(scope.matches(anime_folder,non_anime))
        nested=media(self.two,"Comedy/Anime",jid="2"*32)
        self.assertFalse(scope.matches(nested,non_anime))
        tagged=media(self.two,"Comedy",jid="3"*32)
        tagged["genres"]=["Anime","Fantasy"]
        self.assertFalse(scope.matches(tagged,non_anime))
        western=media(self.two,"Animation",jid="4"*32)
        western["genres"]=["Animation","Comedy"]
        self.assertTrue(scope.matches(western,non_anime))
        name_only=media(self.two,"Comedy",name="The.Anime.Movie.2005.mkv",jid="5"*32)
        self.assertTrue(scope.matches(name_only,non_anime))

    def test_movies_only_scope_applies_to_search_and_stage(self):
        rows=[self.outside,self.horror,self.drama,self.tv,
              media(self.two,"Anime",jid="f"*32)]
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE searches (jellyfin_id TEXT, outcome TEXT,"
                   " searched_at INTEGER, results_json TEXT)")
        with patch.object(search.priorities,"active_coverage_queue",return_value=None), \
             patch.object(search,"query_for",return_value={"language":"ja"}):
            selected=search.pick(rows,db,600,scope=scope.MOVIES_NO_ANIME)
        self.assertEqual({x["id"] for x in selected},
                         {self.outside["jellyfin_id"],self.horror["jellyfin_id"],
                          self.drama["jellyfin_id"]})
        inventory={r["jellyfin_id"]:r for r in rows}
        found=[(r["jellyfin_id"],json.dumps({"candidates":[
            {"subtitle_id":i+1,"score":90,"provider":"opensubtitles"}]}))
            for i,r in enumerate(rows)]
        with patch.object(stage,"rejected_duration_candidates",return_value=set()), \
             patch.object(stage.priorities,"active_coverage_queue",return_value=None), \
             patch.object(stage,"identity_ok",return_value=True):
            selected=stage.choices(inventory,found,set(),100,"all",
                                   scope=scope.MOVIES_NO_ANIME)
        self.assertEqual({x["row"]["jellyfin_id"] for x in selected},
                         {self.outside["jellyfin_id"],self.horror["jellyfin_id"],
                          self.drama["jellyfin_id"]})

    def test_existing_all_scope_unchanged(self):
        self.assertTrue(scope.matches(self.outside,"all"))
        self.assertTrue(scope.matches(self.tv,"all"))
        with self.assertRaises(ValueError):
            scope.matches(self.horror,"wrong")

    def test_search_uses_existing_persistent_history_and_scope(self):
        rows=[self.outside,self.horror,self.drama]
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE searches (jellyfin_id TEXT, outcome TEXT,"
                   " searched_at INTEGER, results_json TEXT)")
        import time
        db.execute("INSERT INTO searches VALUES (?,?,?,?)",
                   (self.horror["jellyfin_id"],"none",int(time.time()),
                    json.dumps({"strategy_version":5})))
        db.commit()
        with patch.object(search.priorities,"active_coverage_queue",return_value=None), \
             patch.object(search,"query_for",return_value={"language":"ja"}):
            selected=search.pick(rows,db,600,scope=scope.SCOPE)
        self.assertEqual([x["id"] for x in selected],[self.drama["jellyfin_id"]])

    def test_staging_excludes_other_folders(self):
        rows=[self.horror,self.drama,self.outside]
        db={x["jellyfin_id"]:x for x in rows}
        found=[(x["jellyfin_id"],json.dumps({"candidates":[
            {"subtitle_id":i+1,"score":90,"provider":"opensubtitles"}]}))
            for i,x in enumerate(rows)]
        with patch.object(stage,"rejected_duration_candidates",return_value=set()), \
             patch.object(stage.priorities,"active_coverage_queue",return_value=None), \
             patch.object(stage,"identity_ok",return_value=True):
            selected=stage.choices(db,found,set(),15,"all",scope=scope.SCOPE)
        self.assertEqual({x["row"]["jellyfin_id"] for x in selected},
                         {self.horror["jellyfin_id"],self.drama["jellyfin_id"]})


if __name__=="__main__":
    unittest.main()
