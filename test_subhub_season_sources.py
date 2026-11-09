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
