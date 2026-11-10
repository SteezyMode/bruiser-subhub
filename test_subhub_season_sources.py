"""Offline regression tests for source-first season selection; never network."""
from collections import Counter
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from tools import subhub_season_sources as selected


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"queue.db"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
            CREATE TABLE media (
              path TEXT PRIMARY KEY,jellyfin_id TEXT,title TEXT,series TEXT,
              kind TEXT,season TEXT,episode TEXT,en_text INTEGER,ja_present INTEGER
            );
            CREATE TABLE tasks (
              path TEXT,target TEXT,action TEXT,state TEXT,active INTEGER
            );
            """)
            for ep,action,ja in (
                (1,"search_ja",1),
                (2,"search_ja",0),
                (3,"download_saved_ja",0),
                (4,"align_existing_staged_ja",0),
                (5,"review_saved_ja",0),
                (6,"validate_english_for_ja_fallback",0),
            ):
                path=f"/mnt/BigDisk/Video/S01E{ep:02d}.mkv"
                db.execute("INSERT INTO media VALUES(?,?,?,?,?,?,?,?,?)",
                  (path,f"{ep:032x}","episode","It's Always Sunny in Philadelphia",
                   "Episode","1",str(ep),1,ja))
                db.execute("INSERT INTO tasks VALUES(?,?,?,?,?)",
                  (path,"ja",action,"pending",1))
            db.execute("INSERT INTO media VALUES(?,?,?,?,?,?,?,?,?)",(
              "/mnt/BigDisk/Video/S02E01.mkv","f"*32,"other",
              "It's Always Sunny in Philadelphia","Episode","2","1",1,0))
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?)",(
              "/mnt/BigDisk/Video/S02E01.mkv","ja","search_ja","pending",1))
        self.path.chmod(0o600)

    def test_shared_search_retains_old_ja_candidates_on_retry_and_rejects_for_review(self):
        from tools import ja_first_search_pilot as search
        root=Path(self.tmp.name)/"source-inventory"
        root.mkdir(mode=0o700)
        file=root/"japanese-search.sqlite3"
        job={"id":"a"*32,"row":{"kind":"Episode","title":"Series E01"}}
        good={"provider":"opensubtitles","subtitle_id":"123456",
              "filename":"Example.S01E01.ja.srt","language":"ja"}
        rejected={"provider":"subdl","subtitle_id":"other",
                  "filename":"Example.S01E02.ja.srt","language":"ja"}
        with mock.patch.object(search,"DB",file):
            with search.open_db() as db:
                search.save_attempt(db,job,"plausible",3,[("plausible",good)])
                search.save_attempt(db,job,"in_progress")
                search.save_attempt(db,job,"error")
                search.save_attempt(db,job,"none",1,[("reject",rejected)])
                row=db.execute("SELECT outcome,results_json FROM searches "
                               "WHERE jellyfin_id=?",(job["id"],)).fetchone()
                self.assertEqual(row[0],"plausible")
                import json
                data=json.loads(row[1])
                self.assertEqual(data["candidates"][0]["subtitle_id"],"123456")
                self.assertEqual(data["rejected_candidates"][0]["provider"],"subdl")
                self.assertEqual(data["rejected_candidates"][0]["grade"],"reject")
                self.assertEqual(data["rejected_count"],1)
                first={"id":"b"*32,"row":{"kind":"Episode","title":"Other E02"}}
                search.save_attempt(db,first,"in_progress")
                search.save_attempt(db,first,"error")
                self.assertEqual(db.execute(
                    "SELECT outcome FROM searches WHERE jellyfin_id=?",
                    (first["id"],)).fetchone()[0],"error")

    def test_manual_metadata_fallback_recovers_title_only_subtitles(self):
        # Execute the exact small container worker offline using mocked API replies.
        # An IMDb/hash search can return zero even when title+episode has a JA file.
        import io
        import json
        import sys
        import types
        from tools import ja_first_search_pilot as search
        from types import SimpleNamespace

        original_query = {
            "series_title": "It's Always Sunny in Philadelphia",
            "season": 7, "episode": 2, "language": "ja",
            "imdb_id": "tt0472954", "file_path": "/mnt/tv/S07E02.mkv"
        }

        def exercise(allow_fallback):
            calls = []
            def respond(request, timeout):
                q = json.loads(request.data)
                calls.append(q)
                if q.get("imdb_id") or q.get("file_path"):
                    return io.BytesIO(b'{"total":0,"results":[]}')
                return io.BytesIO(json.dumps({"total":1,"results":[{
                    "provider":"opensubtitles","subtitle_id":"123456",
                    "language":"ja",
                    "filename":"Its.Always.Sunny.in.Philadelphia.S07E02.WEB-DL.DSNP.ja",
                    "matches":["series","season","episode"]
                }]}).encode())
            job = [{"id":"episode-id","query":original_query,
                    "retry_by_title":allow_fallback}]
            fake_cfg = types.ModuleType("config")
            fake_cfg.get_settings = lambda: SimpleNamespace(api_key="TEST_KEY")
            output = io.StringIO()
            with mock.patch.dict(sys.modules, {"config":fake_cfg}), \\
                 mock.patch("urllib.request.urlopen",side_effect=respond), \\
                 mock.patch("time.sleep"), \\
                 mock.patch.object(sys,"stdin",io.StringIO(json.dumps(job))), \\
                 mock.patch.object(sys,"stdout",output):
                exec(search.CONTAINER_WORKER,{"__name__":"__main__"})
            return json.loads(output.getvalue()),calls

        result,calls=exercise(True)
        self.assertEqual(result["query_variant"],"title_only_fallback")
        self.assertEqual(result["initial_total"],0)
        self.assertEqual(result["total"],1)
        self.assertEqual(len(calls),2)
        self.assertNotIn("imdb_id",calls[1])
        self.assertEqual(calls[1]["file_path"],"")
        self.assertEqual(result["results"][0]["language"],"ja")
        no_retry,calls=exercise(False)
        self.assertEqual(no_retry["query_variant"],"original")
        self.assertEqual(no_retry["total"],0)
        self.assertEqual(len(calls),1)

    def test_scope_only_pending_source_first_same_season(self):
        p=selected.scope("It's Always Sunny in Philadelphia",1,path=self.path)
        self.assertEqual(set(p["ids"]),{f"{n:032x}" for n in (2,3,4)})
        self.assertEqual(p["eligible"],3)
        self.assertEqual(p["skipped"]["already_covered"],1)
        self.assertEqual(p["skipped"]["not_source_ready"],2)

    def test_duplicate_episode_never_automatically_sourced(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO media VALUES(?,?,?,?,?,?,?,?,?)",(
               "/mnt/BigDisk/Video/ALT-S01E02.mkv","a"*32,"alt",
               "It's Always Sunny in Philadelphia","Episode","1","2",1,0))
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?)",(
               "/mnt/BigDisk/Video/ALT-S01E02.mkv","ja","search_ja","pending",1))
        p=selected.scope("It's Always Sunny in Philadelphia",1,path=self.path)
        self.assertNotIn(f"{2:032x}",p["ids"])
        self.assertEqual(p["skipped"]["duplicate_episode"],1)

    def test_untrusted_queue_and_invalid_series_block(self):
        with self.assertRaises(ValueError):
            selected.scope("IASIP",0,path=self.path)
        self.path.chmod(0o644)
        with self.assertRaises(RuntimeError):
            selected.scope("It's Always Sunny in Philadelphia",1,path=self.path)

    def test_preview_requires_no_source_modules_or_provider_calls(self):
        with mock.patch.object(selected,"native") as native, \
             mock.patch.object(selected,"run") as run:
            with mock.patch.object(selected.batch,"DB",self.path):
                self.assertEqual(selected.main([
                  "--series","It's Always Sunny in Philadelphia",
                  "--season","1"]),0)
            native.assert_not_called()
            run.assert_not_called()

    def test_explicit_recheck_respects_exact_show_episode_scope(self):
        selected_items=[{"season":1,"episode":2},{"season":1,"episode":5},
                        {"season":1,"episode":6}]
        result=selected.selected_scope("It's Always Sunny in Philadelphia",
                                     selected_items,recheck=True,path=self.path)
        self.assertEqual(result["eligible"],3)
        self.assertEqual(set(result["ids"]),{f"{n:032x}" for n in (2,5,6)})
        self.assertEqual(result["seasons"],[1])
        with self.assertRaises(RuntimeError):
            selected.selected_scope("It's Always Sunny in Philadelphia",
                [{"season":1,"episode":5}],path=self.path)
        with self.assertRaises(RuntimeError):
            selected.selected_scope("It's Always Sunny in Philadelphia",
                [{"season":1,"episode":1}],recheck=True,path=self.path)
        with self.assertRaises(RuntimeError):
            selected.selected_scope("American Dad!",
                [{"season":1,"episode":2}],recheck=True,path=self.path)
        with self.assertRaises(ValueError):
            selected.selected_scope("It's Always Sunny in Philadelphia",
                [{"season":1,"episode":2},{"season":1,"episode":2}],
                recheck=True,path=self.path)

    def test_explicit_source_repair_includes_held_candidate_not_global_queue(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE tasks SET state='held' "
                       "WHERE path LIKE '%S01E05.mkv'")
        pick=[{"season":1,"episode":5}]
        selected_item=selected.selected_scope(
            "It's Always Sunny in Philadelphia",pick,recheck=True,path=self.path)
        self.assertEqual(selected_item["eligible"],1)
        with self.assertRaisesRegex(RuntimeError,"not_eligible_for_source"):
            selected.selected_scope(
                "It's Always Sunny in Philadelphia",pick,recheck=False,path=self.path)

    def test_general_untagged_audio_review_is_selected_only_by_owner(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE tasks SET target='review',action='review_uncertain' "
                       "WHERE path LIKE '%S01E05.mkv'")
        selected_items=[{"season":1,"episode":5}]
        scoped=selected.selected_scope(
            "It's Always Sunny in Philadelphia",selected_items,
            recheck=True,path=self.path)
        jid=f"{5:032x}"
        self.assertEqual(scoped["reviewed"],[jid])
        self.assertEqual(scoped["ids"],{jid:"/mnt/BigDisk/Video/S01E05.mkv"})
        with self.assertRaises(RuntimeError):
            selected.selected_scope(
                "It's Always Sunny in Philadelphia",selected_items,
                recheck=False,path=self.path)
        with self.assertRaises(RuntimeError):
            selected.selected_scope(
                "American Dad!",selected_items,
                recheck=True,path=self.path)

    def test_audio_review_is_in_memory_and_retains_japanese_publish_gates(self):
        from types import SimpleNamespace
        jid="a"*32
        row={"jellyfin_id":jid,"kind":"Episode","status":
             "review_audio_language_unverified","host_path":"/media/file.mkv",
             "season":2,"episode":1,"series_title":"Example Show"}
        root=Path(self.tmp.name)
        (root/"ja-intake-20261109T000001Z.json").write_text("{}")
        search=mock.Mock()
        search.ROOT=root
        search.private_manifest.return_value={"items":[row]}
        stage=mock.Mock()
        stage.duration_if_safe.return_value=1800
        stage.read_inventory.return_value={jid:row}
        direct=mock.Mock()
        publisher=SimpleNamespace(direct=direct)
        with selected.scoped_audio_review({jid:row["host_path"]},
                [jid],search,stage,publisher) as (approved,blocked):
            self.assertFalse(blocked)
            self.assertEqual(approved[jid]["status"],"ready_ja_search")
            stage.duration_if_safe.assert_called_once_with(row)
            self.assertEqual(stage.read_inventory()[jid]["status"],
                             "ready_ja_search")
            self.assertEqual(publisher.direct.read_inventory(jid)["status"],
                             "ready_ja_search")
            doc=search.private_manifest(root/"ja-intake-20261109T000001Z.json")
            self.assertEqual(doc["items"][0]["status"],"ready_ja_search")
        self.assertEqual(search.private_manifest(
            root/"ja-intake-20261109T000001Z.json")["items"][0]["status"],
                         "review_audio_language_unverified")

    def test_manual_review_source_search_requires_correct_episode_file(self):
        import re
        video=Path(self.tmp.name)/"Example.Show.S02E01.mkv"
        video.write_bytes(b"test")
        search=mock.Mock()
        search.sidecar_present.return_value=False
        search.episode_tags.return_value=[(2,1)]
        search.IMDB=re.compile(r"tt\d{5,12}\Z")
        row={"kind":"Episode","host_path":str(video),
             "status":"ready_ja_search","series_title":"Example Show",
             "season":2,"episode":1,"series_imdb_id":"tt1234567"}
        q=selected.manual_source_query(row,search)
        self.assertEqual(q["series_title"],"Example Show")
        self.assertEqual((q["season"],q["episode"]),(2,1))
        self.assertEqual(q["imdb_id"],"tt1234567")
        search.episode_tags.return_value=[(2,2)]
        self.assertIsNone(selected.manual_source_query(row,search))

    def test_exact_pick_cli_preview_never_uses_providers(self):
        with mock.patch.object(selected,"selected_scope",return_value={
                "eligible":1,"seasons":[1],"ids":{"2"*32:"/some/file"},
                "series":"It's Always Sunny in Philadelphia","skipped":{}}) as scope, \
             mock.patch.object(selected,"native") as native, \
             mock.patch.object(selected,"run") as runner:
            self.assertEqual(selected.main([
                "--series","It's Always Sunny in Philadelphia",
                "--pick","S01E002","--recheck"]),0)
            scope.assert_called_once()
            native.assert_not_called()
            runner.assert_not_called()

    def test_run_uses_existing_source_lock_and_reconciles(self):
        src={"series":"It's Always Sunny in Philadelphia","season":1,
             "ids":{"b"*32:"/verified/video.mkv"},"eligible":1,"skipped":{}}
        auto=mock.Mock()
        auto.lock.return_value=9
        auto.native_search_disabled.return_value=True
        auto.config.return_value={}
        search,stage,publish=(mock.Mock(),mock.Mock(),mock.Mock())
        with mock.patch.object(selected,"scope",return_value=src), \
             mock.patch.object(selected,"native",return_value=(
                 auto,search,stage,publish)), \
             mock.patch.object(selected,"find_japanese",return_value=Counter({"none":1})), \
             mock.patch.object(selected,"stage_japanese",return_value=Counter()), \
             mock.patch.object(selected,"publish_japanese",return_value=Counter()), \
             mock.patch.object(selected,"reconcile",return_value=0) as reconcile, \
             mock.patch.object(selected.os,"close") as close:
            self.assertEqual(selected.run("It's Always Sunny in Philadelphia",1),0)
        auto.lock.assert_called_once()
        reconcile.assert_called_once()
        close.assert_called_once_with(9)


    def test_scoped_source_runner_routes_only_owner_selected_reviewed_episode(self):
        from contextlib import contextmanager
        jid="a"*32
        path="/mnt/2TB/Plex Expansion/S02E01.mkv"
        src={"series":"Example Show","season":2,"ids":{jid:path},
             "reviewed":[jid],"eligible":1,"skipped":{}}
        approved={jid:{"jellyfin_id":jid,"status":"ready_ja_search",
                       "host_path":path}}
        @contextmanager
        def permitted(*args,**kwargs):
            yield approved,{}
        auto=mock.Mock()
        auto.lock.return_value=7
        auto.native_search_disabled.return_value=True
        auto.config.return_value={}
        search,stage,publish=mock.Mock(),mock.Mock(),mock.Mock()
        with mock.patch.object(selected,"selected_scope",return_value=src), \
             mock.patch.object(selected,"native",return_value=(
                 auto,search,stage,publish)), \
             mock.patch.object(selected,"scoped_audio_review",side_effect=permitted), \
             mock.patch.object(selected,"find_japanese",
                               return_value=Counter({"plausible":1})) as searched, \
             mock.patch.object(selected,"stage_japanese",
                               return_value=Counter({"staged":1})) as staged, \
             mock.patch.object(selected,"publish_japanese",
                               return_value=Counter({"published_new":1})) as published, \
             mock.patch.object(selected,"reconcile",return_value=0), \
             mock.patch.object(selected.os,"close") as closed:
            self.assertEqual(selected.run("Example Show",2,
                [{"season":2,"episode":1}],recheck=True),0)
        self.assertEqual(searched.call_args.args[0],{jid:path})
        self.assertEqual(searched.call_args.kwargs["approved_reviews"],approved)
        self.assertEqual(staged.call_args.args[0],{jid:path})
        self.assertEqual(published.call_args.args[0],{jid:path})
        closed.assert_called_once_with(7)

    def test_old_installed_source_helper_missing_duration_function(self):
        import os
        from types import SimpleNamespace
        dbpath=Path(self.tmp.name)/"staging.sqlite3"
        with sqlite3.connect(dbpath) as db:
            db.execute("CREATE TABLE staged (jellyfin_id TEXT,"
                       "subtitle_id TEXT,status TEXT)")
            db.executemany("INSERT INTO staged VALUES (?,?,?)",[
                ("a"*32,"1234","held_duration_mismatch"),
                ("b"*32,"5678","staged")])
        dbpath.chmod(0o600)
        old=SimpleNamespace(STAGE_DB=dbpath)
        self.assertEqual(selected.saved_duration_rejections(old),
                         {("a"*32,"1234")})
        old.rejected_duration_candidates=lambda:{("c"*32,"9999")}
        self.assertEqual(selected.saved_duration_rejections(old),
                         {("c"*32,"9999")})

    def test_recheck_stage_accepts_old_host_helper_without_duration_method(self):
        from types import SimpleNamespace
        jid="b"*32
        video="/mnt/2TB/Plex Expansion/Example/S04E09.mkv"
        stage=SimpleNamespace(
            STAGE_DB=Path(self.tmp.name)/"legacy-stage.sqlite3",
            read_inventory=lambda:{jid:{
                "jellyfin_id":jid,"host_path":video,
                "status":"ready_ja_search"}},
            read_saved_searches=lambda:[],
            read_staged=lambda:set())
        with sqlite3.connect(stage.STAGE_DB) as db:
            db.execute("CREATE TABLE staged (jellyfin_id TEXT,"
                       "subtitle_id TEXT,status TEXT)")
        stage.STAGE_DB.chmod(0o600)
        result=selected.stage_japanese({jid:video},stage,1,recheck=True)
        self.assertEqual(dict(result),{})

    def test_real_publication_failure_is_recorded_not_silent(self):
        jid="d"*32
        publisher=mock.Mock()
        publisher.stages.return_value=[(jid,"1001","digest")]
        publisher.unique_titles.return_value={jid:[("1001","digest")]}
        publisher.choose.side_effect=RuntimeError("timing_gate_not_met")
        with mock.patch.object(selected,"mark_publication_held") as hold:
            result=selected.publish_japanese({jid:"/video.mkv"},publisher,1)
        self.assertEqual(result["held"],1)
        hold.assert_called_once_with(jid,"timing_gate_not_met")

    def test_multiseason_run_continues_after_one_season_fails(self):
        plan={"seasons":[2,4],"ids":{"a"*32:"/media/S02E01.mkv"},
              "eligible":2,"reviewed":[],"skipped":{}}
        calls=[]
        def fake_run(series,season,picks,recheck=False):
            calls.append((series,season,recheck))
            if season==2:
                raise AttributeError("missing_host_helper")
            return 0
        with mock.patch.object(selected,"selected_scope",return_value=plan), \
             mock.patch.object(selected,"run",side_effect=fake_run):
            result=selected.main([
                "--series","Example Show","--pick","S02E001",
                "--pick","S04E009","--recheck","--run"])
        self.assertEqual(result,1)
        self.assertEqual([x[1] for x in calls],[2,4])

    def test_zero_work_cannot_claim_success(self):
        src={"series":"It's Always Sunny in Philadelphia","season":12,
             "ids":{"a"*32:"/verified/S12E01.mkv"},"eligible":1,"skipped":{}}
        auto=mock.Mock()
        auto.lock.return_value=8
        auto.config.return_value={}
        auto.native_search_disabled.return_value=True
        with mock.patch.object(selected,"scope",return_value=src), \
             mock.patch.object(selected,"native",return_value=(
                 auto,mock.Mock(),mock.Mock(),mock.Mock())), \
             mock.patch.object(selected,"find_japanese",return_value=Counter()), \
             mock.patch.object(selected,"stage_japanese",return_value=Counter()), \
             mock.patch.object(selected,"publish_japanese",return_value=Counter()), \
             mock.patch.object(selected,"reconcile",return_value=0), \
             mock.patch.object(selected.os,"close") as close:
            with self.assertRaisesRegex(RuntimeError,"no_operations_performed"):
                selected.run(src["series"],12)
        close.assert_called_once_with(8)

    def test_no_eligible_tasks_is_noop(self):
        src={"series":"IASIP","season":1,
             "ids":{},"eligible":0,"skipped":{}}
        with mock.patch.object(selected,"scope",return_value=src), \
             mock.patch.object(selected,"native") as native:
            self.assertEqual(selected.run("IASIP",1),0)
            native.assert_not_called()


if __name__=="__main__":
    unittest.main()
