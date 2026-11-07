"""Offline tests for series/season-ordered batch planning. No GPU or media writes."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from tools import subhub_translation_batch as batch


class SeasonBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dbpath = Path(self.temp.name) / "queue.sqlite3"
        db = sqlite3.connect(self.dbpath)
        db.executescript("""
            CREATE TABLE media (
                path TEXT PRIMARY KEY,jellyfin_id TEXT,title TEXT,series TEXT,
                kind TEXT,season TEXT,episode TEXT,en_text INTEGER,ja_present INTEGER
            );
            CREATE TABLE tasks (
                path TEXT,target TEXT,action TEXT,state TEXT,active INTEGER
            );
        """)
        for n in range(1, 9):
            path=f"/media/IASIP/S01E{n:02d}.mkv"
            db.execute("INSERT INTO media VALUES(?,?,?,?,?,?,?,?,?)",
                (path,f"{n:032x}",f"Episode {n}","It's Always Sunny in Philadelphia",
                 "Episode","1",str(n),1,1 if n==1 else 0))
            action = ("search_ja" if n==3 else
                      "recover_english_for_ja_fallback" if n==5 else
                      "validate_english_for_ja_fallback")
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?)",
                (path,"ja",action,"pending",1))
        # Different series and seasons must never leak into a selection.
        db.execute("INSERT INTO media VALUES(?,?,?,?,?,?,?,?,?)",
            ("/media/ad/S20E01.mkv","f"*32,"Other", "American Dad!",
             "Episode","20","1",1,0))
        db.commit()
        db.close()
        self.dbpath.chmod(0o600)

    def test_series_catalog_is_from_actual_queue_matrix(self):
        entries = batch.catalog(self.dbpath)
        self.assertEqual(entries, [
            {"series":"American Dad!","seasons":[20]},
            {"series":"It's Always Sunny in Philadelphia","seasons":[1]},
        ])

    def test_first_missing_episodes_are_chronological_without_random_replacements(self):
        p = batch.plan("It's Always Sunny in Philadelphia",1,4,path=self.dbpath)
        self.assertEqual([x["episode"] for x in p["items"]],[2,3,4,5])
        self.assertEqual([x["status"] for x in p["items"]],
                         ["ready","blocked","ready","blocked"])
        self.assertEqual((p["ready"],p["blocked"],p["covered"]),(2,2,1))
        self.assertEqual(p["items"][1]["reason"],"japanese_source_first")
        self.assertNotIn("jellyfin_id",p["items"][1])
        self.assertEqual(batch.plan("American Dad!",20,20,path=self.dbpath)["selected"],1)

    def test_can_select_later_season_segment_without_reordering(self):
        p=batch.plan("It's Always Sunny in Philadelphia",1,20,6,path=self.dbpath)
        self.assertEqual([x["episode"] for x in p["items"]],[6,7,8])

    def test_invalid_inputs_and_insecure_db_fail_closed(self):
        for value in (0,41,True):
            with self.assertRaises(ValueError):
                batch.plan("It's Always Sunny in Philadelphia",1,value,path=self.dbpath)
        with self.assertRaises(ValueError):
            batch.plan("IASIP';DROP TABLE",0,20,path=self.dbpath)
        self.dbpath.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError,"private_coverage_queue"):
            batch.catalog(self.dbpath)
        self.dbpath.chmod(0o600)

    def test_no_model_on_preview_and_batch_inherits_existing_engine(self):
        p=batch.plan("It's Always Sunny in Philadelphia",1,20,path=self.dbpath)
        self.assertEqual(p["ready"],5)
        with mock.patch.object(batch,"plan",return_value=p), \
             mock.patch.object(batch,"ENGINE",Path(self.temp.name)/"engine"), \
             mock.patch.object(batch,"WORK",Path(self.temp.name)/"work"):
            engine=batch.ENGINE
            engine.write_text("#!/bin/sh\nexit 0\n")
            engine.chmod(0o700)
            with mock.patch.object(batch.subprocess,"Popen") as proc:
                with mock.patch.object(batch,"run_batch",return_value=0) as runner:
                    self.assertEqual(batch.main([
                      "--series","It's Always Sunny in Philadelphia",
                      "--season","1","--count","20","--run"]),0)
                    runner.assert_called_once()
                proc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
