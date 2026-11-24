"""Offline tests for the consolidated existing SubHub dispatcher."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock
from tools import subhub_auto as auto


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=auto.connection(self.root/"jobs.sqlite3")
        self.addCleanup(self.db.close)
        self.deep=mock.Mock()
        self.deep.REQUIRED_PROVIDERS={"opensubtitles","subdl"}
        self.deep.validate_exhausted.return_value=False
        self.deep.search_record.return_value={}
        self.deep.stage.japanese_sidecar_exists.return_value=False

    def row(self,jid,kind="Movie",title="Film",genre=(),folder="Movies"):
        video=self.root/folder/(jid+".mkv")
        video.parent.mkdir(exist_ok=True)
        video.write_bytes(b"video")
        return {"jellyfin_id":jid,"host_path":str(video),"kind":kind,
                "status":"ready_ja_search","title":title,"genres":list(genre)}

    def test_fresh_titles_before_repeated_holds(self):
        old=self.row("a"*32,title="A old")
        fresh=self.row("b"*32,title="B fresh")
        episode=self.row("c"*32,kind="Episode")
        auto.update(self.db,old,"source_retry",retry_after=0)
        got=auto.ordered([old,episode,fresh],self.db,"source",self.deep)
        self.assertEqual([r["jellyfin_id"] for r in got],
                         [fresh["jellyfin_id"],episode["jellyfin_id"],old["jellyfin_id"]])

    def test_cooldown_and_anime_excluded(self):
        old=self.row("a"*32)
        anime=self.row("b"*32,kind="Episode",folder="Anime")
        genre=self.row("c"*32,genre=["Anime"])
        western=self.row("d"*32,kind="Episode",genre=["Animation"])
        auto.update(self.db,old,"source_retry",retry_after=auto.now()+100)
        self.assertEqual(auto.ordered([old,anime,genre,western],self.db,
                                      "source",self.deep),[western])

    def test_quota_is_not_exhaustion(self):
        row=self.row("a"*32)
        self.deep.search_record.return_value={"_outcome":"deferred"}
        self.assertEqual(auto.ordered([row],self.db,"translation",self.deep),[])
        self.deep.run.return_value={"result":"retry_source","reason":"provider_quota"}
        runner=mock.Mock()
        report=auto.dispatch([row],self.db,"source",self.deep,runner=runner)
        self.assertEqual(report["retry"],1)
        self.assertEqual(report["source_ready"],0)
        self.assertEqual(auto.state_for(self.db,row["jellyfin_id"])["state"],"source_retry")
        runner.assert_not_called()

    def test_verified_proof_routes_to_translation_not_source(self):
        row=self.row("a"*32)
        self.deep.validate_exhausted.return_value=True
        self.deep.search_record.return_value={"candidates":[]}
        self.assertEqual(auto.ordered([row],self.db,"source",self.deep),[])
        self.assertEqual(auto.ordered([row],self.db,"translation",self.deep),[row])
        self.deep.search_record.return_value={"candidates":[{"provider":"subf2m"}]}
        self.assertEqual(auto.ordered([row],self.db,"translation",self.deep),[])

    def test_individual_exception_does_not_stop_fresh_work(self):
        one=self.row("a"*32,title="A")
        two=self.row("b"*32,title="B")
        self.deep.run.side_effect=[RuntimeError("bad video"),
                                   {"result":"covered","reason":"source_repaired"}]
        result=auto.dispatch([one,two],self.db,"source",self.deep)
        self.assertEqual(result["retry"],1)
        self.assertEqual(result["covered"],1)
        self.assertEqual(self.deep.run.call_count,2)

    def test_translation_rechecks_proof_and_counts_only_published_file(self):
        row=self.row("a"*32)
        self.deep.validate_exhausted.return_value=True
        self.deep.search_record.return_value={"candidates":[]}
        video=Path(row["host_path"])
        def publish(cmd):
            self.assertIn("--source-exhausted-auto",cmd)
            self.assertNotIn("--explicit-movie-pilot",cmd)
            video.with_name(video.stem+".ja.PLaMo8B.srt").write_text("subtitles")
            return 0
        result=auto.dispatch([row],self.db,"translation",self.deep,
                             runner=publish,quiet=lambda:True)
        self.assertEqual(result["published"],1)

    def test_no_translation_outside_quiet_window(self):
        row=self.row("a"*32)
        self.deep.validate_exhausted.return_value=True
        self.deep.search_record.return_value={"candidates":[]}
        runner=mock.Mock()
        auto.dispatch([row],self.db,"translation",self.deep,
                      runner=runner,quiet=lambda:False)
        runner.assert_not_called()


if __name__=="__main__":
    unittest.main()
