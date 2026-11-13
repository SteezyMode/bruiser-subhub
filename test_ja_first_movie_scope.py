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
        anime_release=media(
            self.four,
            "Animated/[AnimeRG] Studio Ghibli Film Collection",
            name="Spirited.Away.2001.mkv",jid="6"*32)
        self.assertFalse(scope.matches(anime_release,non_anime))
        self.assertTrue(scope.matches(
            media(self.two,"Animated/Western Animated Films",jid="7"*32),
            non_anime))
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

    def test_movies_all_includes_both_libraries_and_anime_but_not_tv(self):
        all_movies=scope.MOVIES_ALL
        self.assertTrue(scope.matches(self.horror,all_movies))
        self.assertTrue(scope.matches(self.outside,all_movies))
        self.assertTrue(scope.matches(self.drama,all_movies))
        self.assertTrue(scope.matches(media(
            self.four,"Animated/[AnimeRG] Studio Ghibli Film Collection",
            name="Spirited.Away.mkv"),all_movies))
        self.assertFalse(scope.matches(self.tv,all_movies))
        self.assertFalse(scope.matches(media(
            Path("/mnt/2TB/Plex Expansion/Television"),
            "Episodic",name="Fake.mkv"),all_movies))
        self.assertFalse(scope.matches(media(
            Path("/tmp"),"Movies",name="Other.mkv"),all_movies))
        self.assertFalse(scope.matches(media(
            self.two,"../Television",name="Fake.mkv"),all_movies))
        self.assertFalse(scope.matches({
            **self.horror,"host_path":"not-a-path"},all_movies))

    def test_movies_all_search_reuses_existing_scope_filter(self):
        rows=[self.outside,self.horror,self.drama,self.tv,
              media(self.four,"Anime",jid="f"*32)]
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE searches (jellyfin_id TEXT, outcome TEXT,"
                   " searched_at INTEGER, results_json TEXT)")
        with patch.object(search.priorities,"active_coverage_queue",return_value=None), \
             patch.object(search,"query_for",return_value={"language":"ja"}):
            selected=search.pick(rows,db,600,scope=scope.MOVIES_ALL)
        self.assertEqual({x["id"] for x in selected},
                         {r["jellyfin_id"] for r in rows if r["kind"]=="Movie"})

    def test_drama_horror_action_scopes_use_real_genres_and_library_sections(self):
        drama=scope.MOVIES_DRAMA
        horror=scope.MOVIES_HORROR
        action=scope.MOVIES_ACTION
        section=media(self.four,"Drama, Suspense",jid="9"*32)
        self.assertTrue(scope.matches(section,drama))
        self.assertFalse(scope.matches(section,horror))
        self.assertFalse(scope.matches(section,action))
        self.assertTrue(scope.matches(self.horror,horror))
        self.assertTrue(scope.matches(self.outside,action) is False)
        action_folder=media(self.two,"Action",jid="8"*32)
        self.assertTrue(scope.matches(action_folder,action))
        self.assertFalse(scope.matches(action_folder,drama))
        action_genre=media(self.two,"Comedy",jid="7"*32)
        action_genre["genres"]=["Action & Adventure","Thriller"]
        self.assertTrue(scope.matches(action_genre,action))
        self.assertTrue(scope.matches(action_genre,drama))
        self.assertFalse(scope.matches(action_genre,horror))
        drama_genre=media(self.four,"Comedy",jid="6"*32)
        drama_genre["genres"]=["Drama"]
        self.assertTrue(scope.matches(drama_genre,drama))
        self.assertFalse(scope.matches(drama_genre,horror))
        self.assertFalse(scope.matches(self.tv,drama))
        self.assertFalse(scope.matches(
            media(Path("/mnt/2TB/Plex Expansion/Television"),"Drama"),drama))
        self.assertFalse(scope.matches(
            media(self.two,"Comedy/Drama",name="Drama.Film.mkv"),drama))
        self.assertFalse(scope.matches(
            media(self.two,"../Television/Drama",name="Wrong.mkv"),drama))
        self.assertFalse(scope.matches(media(Path("/tmp"),"Drama"),drama))

    def test_drama_only_search_excludes_covered_and_unrelated_films(self):
        rows=[self.horror,self.drama,self.outside,self.tv]
        already_ja=media(self.four,"Drama, Suspense",jid="9"*32)
        already_ja["status"]="existing_japanese_subtitle"
        rows.append(already_ja)
        database=sqlite3.connect(":memory:")
        self.addCleanup(database.close)
        database.execute("CREATE TABLE searches (jellyfin_id TEXT, outcome TEXT,"
                         " searched_at INTEGER, results_json TEXT)")
        with patch.object(search.priorities,"active_coverage_queue",return_value=None), \
             patch.object(search,"query_for",return_value={"language":"ja"}):
            selected=search.pick(rows,database,20,scope=scope.MOVIES_DRAMA)
        self.assertEqual([s["id"] for s in selected],[self.drama["jellyfin_id"]])

    def test_owner_full_missing_movie_refresh_ignores_old_search_and_queue_states(self):
        import time
        # Both real drives and multiple historical provider outcomes.
        older=int(time.time())-40*3600
        rows=[
            self.horror, self.drama,
            media(self.two,"Horror",jid="3"*32),
            media(self.two,"Horror",jid="4"*32),
            media(self.two,"Horror",jid="5"*32),
            media(self.two,"Horror",jid="6"*32),
            self.tv,
        ]
        rows[4]["status"]="existing_japanese_subtitle"
        rows[5]["status"]="japanese_audio"
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE searches (jellyfin_id TEXT,outcome TEXT,"
                   "searched_at INTEGER,results_json TEXT)")
        for row,outcome,when in (
            (self.horror,"none",older),
            (self.drama,"review",older),
            (rows[2],"plausible",older),
            (rows[3],"partial",older),
            (rows[4],"none",older),
            (rows[5],"review",older)):
            db.execute("INSERT INTO searches VALUES(?,?,?,?)",
                       (row["jellyfin_id"],outcome,when,
                        json.dumps({"strategy_version":5})))
        db.commit()
        # A legacy queue held state must not block a deliberate owner recheck.
        held={r["jellyfin_id"]:("align_existing_staged_ja","held",1,
                                r["host_path"]) for r in rows
              if r.get("host_path")}
        with patch.object(search.priorities,"active_coverage_queue",return_value=held), \
             patch.object(search,"query_for",return_value={"language":"ja"}):
            normal=search.pick(rows,db,50,scope="movies-all")
            refresh=search.pick(rows,db,50,scope="movies-all",rescan_missing=True)
        self.assertEqual(normal,[])
        self.assertEqual({x["id"] for x in refresh},
                         {self.horror["jellyfin_id"],self.drama["jellyfin_id"],
                          rows[2]["jellyfin_id"],rows[3]["jellyfin_id"]})
        self.assertEqual(len(refresh),4)
        with self.assertRaises(ValueError):
            search.pick(rows,db,50,scope="all",rescan_missing=True)
        with self.assertRaises(ValueError):
            search.pick(rows,db,50,scope="movies-all",
                        rescan_missing=True,retry_none_after_days=3)

    def test_owner_full_refresh_skips_same_allowance_window_and_respects_budget(self):
        import time
        now=int(time.time())
        rows=[self.horror,self.drama,media(self.two,"Horror",jid="3"*32)]
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE searches (jellyfin_id TEXT,outcome TEXT,"
                   "searched_at INTEGER,results_json TEXT)")
        db.executemany("INSERT INTO searches VALUES(?,?,?,?)",[
            (self.horror["jellyfin_id"],"none",now-3600,
             json.dumps({"strategy_version":5})),
            (self.drama["jellyfin_id"],"review",now-21*3600,
             json.dumps({"strategy_version":5})),
            (rows[2]["jellyfin_id"],"none",now-21*3600,
             json.dumps({"strategy_version":5})),
        ])
        db.commit()
        with patch.object(search.priorities,"active_coverage_queue",return_value=None), \
             patch.object(search,"query_for",return_value={"language":"ja"}):
            selected=search.pick(rows,db,1,scope="movies-all",rescan_missing=True)
            all_selected=search.pick(rows,db,20,scope="movies-all",rescan_missing=True)
        self.assertEqual(len(selected),1)
        self.assertEqual({x["id"] for x in all_selected},
                         {self.drama["jellyfin_id"],rows[2]["jellyfin_id"]})

    def test_full_scan_resume_prioritizes_unfinished_titles_after_provider_reset(self):
        import time
        now=int(time.time())
        rows=[
            media(self.two,"Horror",name="Recently.2024.mkv",jid="1"*32),
            media(self.two,"Horror",name="NeverSearched.2024.mkv",jid="2"*32),
            media(self.two,"Horror",name="OldResult.2024.mkv",jid="3"*32),
            media(self.two,"Horror",name="OlderResult.2024.mkv",jid="4"*32),
            media(self.two,"Horror",name="StillCooling.2024.mkv",jid="5"*32),
        ]
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE searches (jellyfin_id TEXT,outcome TEXT,"
                   "searched_at INTEGER,results_json TEXT)")
        for index,when in ((0,now-26*3600),(2,now-7*86400),
                           (3,now-28*86400),(4,now-2*3600)):
            db.execute("INSERT INTO searches VALUES(?,?,?,?)",
                       (rows[index]["jellyfin_id"],"none",when,
                        json.dumps({"strategy_version":5})))
        db.commit()
        with patch.object(search.priorities,"active_coverage_queue",
                          side_effect=AssertionError("stale queue must not be opened")), \
             patch.object(search,"query_for",return_value={"language":"ja"}):
            first=search.pick(rows,db,2,scope="movies-horror",rescan_missing=True)
            remaining=search.pick(rows,db,10,scope="movies-horror",rescan_missing=True)
        self.assertEqual([x["id"] for x in first],
                         [rows[1]["jellyfin_id"],rows[3]["jellyfin_id"]])
        self.assertEqual([x["id"] for x in remaining],
                         [rows[1]["jellyfin_id"],rows[3]["jellyfin_id"],
                          rows[2]["jellyfin_id"],rows[0]["jellyfin_id"]])
        self.assertNotIn(rows[4]["jellyfin_id"],{x["id"] for x in remaining})

    def test_host_discovery_enforces_actual_backend_request_budget(self):
        import contextlib
        import sys
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/"ja-intake-test.json").write_text("{}")
            ids=["1"*32,"2"*32,"3"*32]
            work=[{"id":jid,
                   "row":{"jellyfin_id":jid,"kind":"Movie",
                          "title":"Example","year":2020},
                   "query":{"title":"Example","year":2020,
                            "imdb_id":"tt1234567"}} for jid in ids]
            for per_job_max, expected_calls in ((1,2),(2,1)):
                calls=[]
                def worker(command,**kwargs):
                    job=json.loads(kwargs["input"])[0]
                    cap=job["request_limit"]
                    calls.append((job["id"],cap))
                    made=min(cap,per_job_max)
                    payload={"id":job["id"],"ok":True,
                             "total":0,"results":[],"requests_made":made,
                             "provider_gates":{"opensubtitles":"ok"},
                             "incomplete_providers":[],"strategy_version":5,
                             "query_variant":"test"}
                    return SimpleNamespace(returncode=0,
                                           stdout=json.dumps(payload),
                                           stderr="")
                with self.subTest(per_job_max=per_job_max), \
                     patch.object(search,"ROOT",folder), \
                     patch.object(search,"private_manifest",
                                  return_value={"items":[]}), \
                     patch.object(search,"open_db",
                                  return_value=contextlib.nullcontext(None)), \
                     patch.object(search,"save_attempt"), \
                     patch.object(search,"pick",return_value=work), \
                     patch.object(search.subprocess,"run",side_effect=worker), \
                     patch.object(search.time,"sleep"), \
                     patch.object(sys,"argv",["ja_first_search_pilot.py",
                                             "--budget","2","--scope",
                                             "movies-horror"]):
                    search.main()
                self.assertEqual(len(calls),expected_calls)
                self.assertEqual(calls[0],(ids[0],2))
                if expected_calls==2:
                    self.assertEqual(calls[1],(ids[1],1))

    def test_verified_original_language_title_can_unlock_review_without_guessing(self):
        film_row={**self.drama,"title":"Guilty of Romance","year":2011,
                  "original_title":"恋の罪"}
        japanese={"provider":"opensubtitles","subtitle_id":"123456",
                  "language":"ja","filename":"",
                  "release_info":"恋の罪","matches":["title"]}
        self.assertTrue(stage.identity_ok(film_row,japanese))
        self.assertFalse(stage.identity_ok(
            film_row,{**japanese,"release_info":"恋の罪 2019"}))
        self.assertFalse(stage.identity_ok(
            film_row,{**japanese,"release_info":"恋の罪 Extended","matches":[]}))
        self.assertFalse(stage.identity_ok(
            {**film_row,"original_title":""},japanese))
        self.assertFalse(stage.identity_ok(
            film_row,{**japanese,"release_info":"罪","matches":["title"]}))

        french={**self.horror,"title":"Eyes Without a Face","year":1960,
                "original_title":"Les yeux sans visage"}
        original={"provider":"opensubtitles","subtitle_id":"234567",
                  "language":"ja","filename":"Les_Yeux_sans_visage_1960-720pJapanese",
                  "release_info":"Les Yeux sans visage (1960)","matches":["title"]}
        self.assertTrue(stage.identity_ok(french,original))
        self.assertFalse(stage.identity_ok(
            french,{**original,"release_info":"Les Yeux sans visage 1988",
                    "filename":"Les Yeux sans visage"}))

    def test_saved_subdl_japanese_zip_slug_matches_exact_movie_and_remote_id(self):
        movie={**self.drama,"title":"Withnail & I","year":1987}
        result={"provider":"subdl","subtitle_id":"123456-449088",
                "filename":"SUBDL.com::_withnail-and-i_japanese_449088.zip",
                "release_info":"Withnail And I","language":"ja"}
        self.assertTrue(stage.movie_identity_ok(movie,result))
        self.assertFalse(stage.movie_identity_ok(
            movie,{**result,"subtitle_id":"123456-449089"}))
        self.assertFalse(stage.movie_identity_ok(
            movie,{**result,"filename":"SUBDL.com::_withnail-and-ii_japanese_449088.zip"}))
        self.assertFalse(stage.movie_identity_ok(
            movie,{**result,"release_info":"Withnail and I 2002"}))
        self.assertFalse(stage.movie_identity_ok(
            movie,{**result,"filename":"Withnail and I","release_info":"Withnail And I"}))

    def test_numbered_sequel_full_title_alias_recovers_saved_opensubtitles(self):
        row={**self.horror,
             "title":"A Nightmare on Elm Street Part 2: Freddy's Revenge",
             "year":1985}
        release={"provider":"opensubtitles","subtitle_id":"123456",
                 "language":"ja","matches":["title"],
                 "filename":"A.Nightmare.On.Elm.Street.2.Freddys.Revenge.1985.720p.BrRip.x264",
                 "release_info":""}
        self.assertTrue(stage.identity_ok(row,release))
        self.assertFalse(stage.identity_ok(row,{
            **release,"filename":"A.Nightmare.On.Elm.Street.3.Freddys.Revenge.1985"}))
        self.assertFalse(stage.identity_ok(row,{
            **release,"filename":"A.Nightmare.On.Elm.Street.2.1985"}))
        self.assertFalse(stage.identity_ok(row,{
            **release,"filename":"A.Nightmare.On.Elm.Street.2.Freddys.Revenge.1986"}))
        self.assertFalse(stage.identity_ok(row,{
            **release,"release_info":"A.Nightmare.On.Elm.Street.2.1988"}))
        self.assertFalse(stage.identity_ok(row,{
            **release,"filename":"A.Nightmare.On.Elm.Street.2.Freddys.Revenge.720p"}))
        self.assertFalse(stage.identity_ok(row,{
            **release,"language":"en"}))

    def test_subdl_concatenated_zip_upload_suffix_is_exact_and_ja_only(self):
        row={**self.horror,
             "title":"A Nightmare on Elm Street 4: The Dream Master",
             "year":1988}
        release={"provider":"subdl","subtitle_id":"1234567-340891",
                 "language":"ja","filename":
                 "SUBDL.com::a.nightmare.on.elm.street.4.the.dream.master340891.zip",
                 "release_info":""}
        self.assertTrue(stage.movie_identity_ok(row,release))
        self.assertFalse(stage.movie_identity_ok(row,{
            **release,"subtitle_id":"1234567-340892"}))
        self.assertFalse(stage.movie_identity_ok(row,{
            **release,"filename":
            "SUBDL.com::a.nightmare.on.elm.street.3.the.dream.master340891.zip"}))
        self.assertFalse(stage.movie_identity_ok(row,{
            **release,"filename":"SUBDL.com::a.nightmare.on.elm.street.4340891.zip"}))
        self.assertFalse(stage.movie_identity_ok(row,{
            **release,"filename":"unrelated.nightmare.on.elm.street.4.the.dream.master340891.zip"}))
        self.assertFalse(stage.movie_identity_ok(row,{
            **release,"release_info":"The Dream Master 1999"}))
        self.assertFalse(stage.movie_identity_ok(row,{
            **release,"language":"en"}))
        self.assertFalse(stage.movie_identity_ok(row,{
            **release,"provider":"opensubtitles"}))

    def test_catalog_keeps_real_jellyfin_original_title_without_provider_calls(self):
        import tempfile
        from tools import ja_first_catalog_manifest as intake
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"Guilty.of.Romance.2011.mkv"
            path.touch()
            data={"Id":"a"*32,"Type":"Movie","Name":"Guilty of Romance",
                  "OriginalTitle":"恋の罪","Path":str(path),
                  "ProductionYear":2011,
                  "MediaStreams":[{"Type":"Audio","Language":"en"}],
                  "ProviderIds":{"Imdb":"tt1234567"}}
            result=intake.classify(
                data,{},[(Path(tmp),Path("/media/expansion-video"))],{})
        self.assertEqual(result["original_title"],"恋の罪")
        self.assertEqual(result["status"],"ready_ja_search")

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

    def test_opt_in_genre_only_no_match_retry_preserves_all_other_holds(self):
        import time
        rows=[self.drama,self.outside,self.horror,self.tv]
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE searches (jellyfin_id TEXT,outcome TEXT,"
                   "searched_at INTEGER,results_json TEXT)")
        ago=int(time.time())-8*86400
        for row in rows:
            db.execute("INSERT INTO searches VALUES(?,?,?,?)",
                       (row["jellyfin_id"],"none",ago,
                        json.dumps({"strategy_version":5})))
        db.commit()
        with patch.object(search.priorities,"active_coverage_queue",return_value=None), \
             patch.object(search,"query_for",return_value={"language":"ja"}):
            normal=search.pick(rows,db,20,scope=scope.MOVIES_DRAMA)
            retry=search.pick(rows,db,20,scope=scope.MOVIES_DRAMA,
                              retry_none_after_days=7)
            too_early=search.pick(rows,db,20,scope=scope.MOVIES_DRAMA,
                                  retry_none_after_days=9)
        self.assertEqual(normal,[])
        self.assertEqual([entry["id"] for entry in retry],
                         [self.drama["jellyfin_id"]])
        self.assertEqual(too_early,[])
        for invalid in (0,31,True):
            with self.assertRaises(ValueError):
                search.pick(rows,db,20,scope=scope.MOVIES_DRAMA,
                            retry_none_after_days=invalid)
        with self.assertRaises(ValueError):
            search.pick(rows,db,20,scope="all",retry_none_after_days=7)

    def test_opt_in_no_match_retry_does_not_repeat_recent_no_match_or_reviews(self):
        import time
        old=int(time.time())-9*86400
        rows=[self.drama,self.horror,self.outside]
        rows[0]["status"]="existing_japanese_subtitle"
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE searches (jellyfin_id TEXT,outcome TEXT,"
                   "searched_at INTEGER,results_json TEXT)")
        for row,outcome,when in zip(rows,
                                    ("none","review","none"),
                                    (old,old,int(time.time())-3600)):
            db.execute("INSERT INTO searches VALUES(?,?,?,?)",
                       (row["jellyfin_id"],outcome,when,
                        json.dumps({"strategy_version":5})))
        db.commit()
        with patch.object(search.priorities,"active_coverage_queue",return_value=None), \
             patch.object(search,"query_for",return_value={"language":"ja"}):
            selected=search.pick(rows,db,20,scope="movies-all",
                                 retry_none_after_days=7)
        self.assertEqual(selected,[])

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
