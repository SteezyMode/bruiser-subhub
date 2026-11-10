"""Offline regression: queue drives JA discovery/staging without category quotas."""
from unittest.mock import patch
import sqlite3
import tempfile
from pathlib import Path
import unittest

from tools import ja_first_priority as priorities
from tools import ja_first_search_pilot as search
from tools import ja_first_stage_saved_batch as stage


def item(jid,kind):
    row={"jellyfin_id":jid,"kind":kind,"status":"ready_ja_search",
         "host_path":"/mnt/BigDisk/Video/"+jid+".mkv","title":jid,
         "year":2024,"imdb_id":"tt12345678",
         "series_title":"Example","season":1,"episode":1,"genres":[]}
    return row


def queue_rows(rows,action="search_ja"):
    return {row["jellyfin_id"]:(action,"pending",40,
                               row["host_path"]) for row in rows}


class CoverageSelectionTests(unittest.TestCase):
    def test_installed_queue_requires_private_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"coverage.sqlite3"
            with sqlite3.connect(path) as db:
                db.executescript("""
                    CREATE TABLE media(jellyfin_id TEXT,path TEXT);
                    CREATE TABLE tasks(path TEXT,target TEXT,action TEXT,
                      state TEXT,priority INTEGER,active INTEGER);
                    INSERT INTO media VALUES('movie','/mnt/Movie.mkv');
                    INSERT INTO tasks VALUES('/mnt/Movie.mkv','ja',
                      'search_ja','pending',40,1);
                """)
            path.chmod(0o600)
            result=priorities.active_coverage_queue(path)
            self.assertEqual(result["movie"][0],"search_ja")
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError,"Unsafe"):
                priorities.active_coverage_queue(path)

    def test_discovery_includes_both_categories_without_reserved_quota(self):
        rows=[item("movie1","Movie"),item("episode1","Episode"),
              item("episode2","Episode"),item("episode3","Episode")]
        ranks=queue_rows(rows)
        ranks["movie1"]=("search_ja","pending",50,rows[0]["host_path"])
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE searches(jellyfin_id TEXT,outcome TEXT,searched_at INTEGER)")
            with patch.object(priorities,"active_coverage_queue",return_value=ranks), \
                 patch.object(search,"query_for",return_value={"ok":True}):
                selected=search.pick(rows,db,3)
        ids={x["id"] for x in selected}
        self.assertEqual(ids,{"episode1","episode2","episode3"})

    def test_deferred_or_held_discovery_not_searched(self):
        rows=[item("a","Movie"),item("b","Episode"),item("c","Episode")]
        ranks=queue_rows(rows)
        ranks["a"]=("align_existing_staged_ja","pending",10,rows[0]["host_path"])
        ranks["b"]=("search_ja","held",40,rows[1]["host_path"])
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE searches(jellyfin_id TEXT,outcome TEXT,searched_at INTEGER)")
            with patch.object(priorities,"active_coverage_queue",return_value=ranks), \
                 patch.object(search,"query_for",return_value={"ok":True}):
                selected=search.pick(rows,db,3)
        self.assertEqual([x["id"] for x in selected],["c"])

    def test_v3_negative_search_is_rechecked_once_but_v4_is_not(self):
        import json
        import time
        rows=[item("v3","Movie"),item("v4","Movie"),item("good","Movie")]
        ranks=queue_rows(rows)
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE searches("
                       "jellyfin_id TEXT,outcome TEXT,searched_at INTEGER,"
                       "results_json TEXT)")
            now=int(time.time())
            for jid,kind,version in [
                ("v3","none",3),("v4","none",4),("good","plausible",3)]:
                db.execute("INSERT INTO searches VALUES(?,?,?,?)",(
                    jid,kind,now,json.dumps({"strategy_version":version})))
            with patch.object(priorities,"active_coverage_queue",return_value=ranks), \
                 patch.object(search,"query_for",return_value={"title":"test"}):
                chosen=search.pick(rows,db,10)
        self.assertEqual([x["id"] for x in chosen],["v3"])

    def test_staging_prioritizes_saved_candidate_not_media_type(self):
        rows=[item("mov","Movie"),item("ep","Episode")]
        ranks=queue_rows(rows,"download_saved_ja")
        ranks["ep"]=("download_saved_ja","pending",20,rows[1]["host_path"])
        ranks["mov"]=("download_saved_ja","pending",23,rows[0]["host_path"])
        inventory={r["jellyfin_id"]:r for r in rows}
        history=[("mov",'{"candidates":[{"subtitle_id":"101","score":100}]}'),
                 ("ep",'{"candidates":[{"subtitle_id":"102","score":75}]}')]
        with patch.object(priorities,"active_coverage_queue",return_value=ranks), \
             patch.object(stage,"identity_ok",return_value=True):
            chosen=stage.choices(inventory,history,set(),1,"all")
        self.assertEqual([x["row"]["jellyfin_id"] for x in chosen],["ep"])

    def test_same_cycle_search_hit_can_be_staged(self):
        row=item("newhit","Episode")
        history=[("newhit",'{"candidates":[{"subtitle_id":"104","score":99}]}')]
        with patch.object(priorities,"active_coverage_queue",
                          return_value=queue_rows([row])), \
             patch.object(stage,"identity_ok",return_value=True):
            result=stage.choices({"newhit":row},history,set(),3,"all")
        self.assertEqual([x["row"]["jellyfin_id"] for x in result],["newhit"])


if __name__=="__main__":
    unittest.main()
