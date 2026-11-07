"""Offline tests: exact S12 fallback and source-first safety guards."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import re

TOOLS=str(Path(__file__).resolve().parent/"tools")
sys.path.insert(0,TOOLS)
try:
    import translate_iasip_s12_held as fallback
finally:
    sys.path.remove(TOOLS)


def candidates():
    return {f"{e:032x}":{
        "kind":"Episode","series_title":fallback.SERIES,
        "season":12,"episode":e,"jellyfin_id":f"{e:032x}",
        "host_path":f"/mnt/BigDisk/Video/Television/IASIP/S12E{e:02d}.mkv",
        "status":"ready_ja_search"}
        for e in (4,5)}


class ScopedFallbackTests(unittest.TestCase):
    def test_live_selected_rows_require_exact_queue_and_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"queue.sqlite3"
            db=sqlite3.connect(file)
            db.executescript("""
                CREATE TABLE media (
                  jellyfin_id TEXT,path TEXT,kind TEXT,title TEXT,
                  series TEXT,season TEXT,episode TEXT,ja_present INTEGER,
                  en_text INTEGER);
                CREATE TABLE tasks (
                  path TEXT,action TEXT,state TEXT,target TEXT,active INTEGER);
            """)
            for jid,s in candidates().items():
                db.execute("INSERT INTO media VALUES (?,?,?,?,?,?,?,?,?)",(
                    jid,s["host_path"],"Episode",f"Episode {s['episode']}",
                    fallback.SERIES,"12",str(s["episode"]),0,1))
                db.execute("INSERT INTO tasks VALUES (?,?,?,?,?)",(
                    s["host_path"],"align_existing_staged_ja","pending","ja",1))
            db.commit()
            db.close()
            ai=SimpleNamespace(JELLYFIN_ID=re.compile(r"[0-9a-f]{32}\Z"),
                QUEUE=file,safe_db=lambda _:sqlite3.connect(file))
            stage=Mock()
            stage.read_inventory.return_value=candidates()
            with patch.object(fallback.Path,"is_file",return_value=True),\
                 patch.object(fallback.Path,"is_symlink",return_value=False):
                chosen=fallback.exact_episode_rows(ai,stage)
            self.assertEqual(sorted(v["episode"] for v in chosen.values()),[4,5])
            # The same JA staged item must NOT authorize fallback if English is gone.
            with sqlite3.connect(file) as db:
                db.execute("UPDATE media SET en_text=0 WHERE episode='5'")
            with patch.object(fallback.Path,"is_file",return_value=True),\
                 patch.object(fallback.Path,"is_symlink",return_value=False):
                with self.assertRaisesRegex(RuntimeError,"preflight_not_ready"):
                    fallback.exact_episode_rows(ai,stage)

    def test_still_fixable_ja_is_published_instead_of_translating(self):
        pub=Mock()
        pub.choose.return_value=("ready_ffsubsync",{},{"provenance":"verified"})
        direct=Mock()
        direct.video_target.return_value=Mock(is_symlink=lambda:False,exists=lambda:False)
        jid="a"*32
        row={"jellyfin_id":jid,"path":"/media/episode.mkv","episode":4}
        self.assertTrue(fallback.validate_prior_source_failure(
            row,pub,direct,[("11111","sha")]))
        pub.publish_selected.assert_called_once()
        pub.mark_completed.assert_called_once_with(jid)

    def test_failed_ja_allows_explicit_fallback_only_for_known_failure(self):
        pub=Mock()
        pub.choose.side_effect=RuntimeError(fallback.EXPECTED_HELD)
        direct=Mock()
        direct.video_target.return_value=Mock(is_symlink=lambda:False,exists=lambda:False)
        row={"jellyfin_id":"b"*32,"path":"/media/episode.mkv","episode":5}
        self.assertFalse(fallback.validate_prior_source_failure(
            row,pub,direct,[("11111","sha")]))
        pub.publish_selected.assert_not_called()
        pub.mark_completed.assert_not_called()

    def test_unrelated_source_failure_cannot_bypass_sourcing(self):
        pub=Mock()
        pub.choose.side_effect=RuntimeError("container_not_running")
        direct=Mock()
        direct.video_target.return_value=Mock(is_symlink=lambda:False,exists=lambda:False)
        row={"jellyfin_id":"b"*32,"path":"/media/episode.mkv","episode":5}
        with self.assertRaisesRegex(RuntimeError,"unexpected_source_qa_failure"):
            fallback.validate_prior_source_failure(row,pub,direct,[("11111","sha")])

    def test_missing_staging_cannot_bypass_source(self):
        pub,direct=Mock(),Mock()
        direct.video_target.return_value=Mock(is_symlink=lambda:False,exists=lambda:False)
        row={"jellyfin_id":"b"*32,"path":"/media/episode.mkv","episode":5}
        with self.assertRaisesRegex(RuntimeError,"source_not_really_staged"):
            fallback.validate_prior_source_failure(row,pub,direct,[])
        pub.choose.assert_not_called()

    def test_preparation_checks_source_before_translation(self):
        jid="c"*32
        ai=Mock()
        ai.private_folder.return_value=Mock(is_symlink=lambda:False,
                  mkdir=lambda **kwargs:None,
                  stat=lambda:SimpleNamespace(st_mode=0o700))
        ai.prepared_source.side_effect=RuntimeError(
            "english_text_source_not_available_yet")
        row={"jellyfin_id":jid,"path":"/media/episode.mkv","episode":4}
        with self.assertRaisesRegex(RuntimeError,"english_text_source_not_available"):
            fallback.prepare_and_translate(ai,row)
        ai.translate.assert_not_called()


if __name__=="__main__":
    unittest.main()
