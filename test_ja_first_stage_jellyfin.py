"""Offline provider-agnostic private staging / publisher compatibility tests.

No Jellyfin calls, no provider allowances, no media files modified.
"""
from pathlib import Path
import hashlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parent/"tools"
_inserted=False
if str(TOOLS) not in sys.path:
    sys.path.insert(0,str(TOOLS))
    _inserted=True
try:
    import ja_first_stage_jellyfin as jf
finally:
    if _inserted:
        sys.path.remove(str(TOOLS))


class JellyfinNativeStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.stage_dir=self.root/"staged"
        self.stage_dir.mkdir(mode=0o700)
        self.stage_db=self.root/"staged.sqlite3"
        self.jid="a"*32
        self.row={
            "jellyfin_id":self.jid,"status":"ready_ja_search",
            "kind":"Episode","series_title":"It's Always Sunny in Philadelphia",
            "series_imdb_id":"tt0472954","season":7,"episode":2,"year":2011,
            "host_path":"/unused/optiplex/s07e02.mkv",
        }
        self.candidate={
            "Id":"subbuzz_opensubtitles.comeyJWZCI6Ijg0OTg1MzEifQ,",
            "ProviderName":"subbuzz",
            "Name":"Its.Always.Sunny.in.Philadelphia.S07E02.WEB-DL.DSNP.ja",
            "ThreeLetterISOLanguageName":"jpn","Format":"srt",
        }
        self.raw=("".join(
            f"{i}\n00:{i//60:02d}:{i%60:02d},000 --> "
            f"00:{i//60:02d}:{i%60:02d},800\n日本語の字幕です。ありがとう。\n\n"
            for i in range(1,105))).encode()
        self.sid,self.hash=jf.numeric_stage_id(self.candidate["Id"])
        self.qa=jf.publisher.validate_srt(self.raw,1200)
        self.metrics=jf.stage_metadata(self.row,self.candidate,self.sid,self.hash,
                                       self.raw,1200,self.qa)

    def test_stage_identity_provenance_and_private_srt_validation(self):
        self.assertEqual(len(self.sid),13)
        self.assertTrue(jf.validate_staged_provenance(
            self.row,self.jid,self.sid,self.metrics))
        self.assertEqual(self.metrics["provider"],"jellyfin")
        self.assertEqual(self.metrics["source_remote_provider"],"subbuzz")
        self.assertEqual(self.metrics["cues"],104)
        self.assertNotIn(self.candidate["Id"],str(self.metrics))
        self.assertNotIn(self.candidate["Id"],jf.stage_filename(self.jid,self.sid))
        self.assertTrue(jf.publisher.STAGE_NAME.fullmatch(
            jf.stage_filename(self.jid,self.sid)))

    def test_false_episode_or_changed_digest_refused(self):
        other=dict(self.row,episode=3)
        with self.assertRaisesRegex(RuntimeError,"identity_changed|not_proven"):
            jf.validate_staged_provenance(other,self.jid,self.sid,self.metrics)
        other_name=dict(self.metrics,source_filename="Its.Always.Sunny.S07E03.ja")
        with self.assertRaisesRegex(RuntimeError,"not_proven"):
            jf.validate_staged_provenance(self.row,self.jid,self.sid,other_name)
        corrupt=dict(self.metrics,source_remote_id_sha256="0"*64)
        with self.assertRaisesRegex(RuntimeError,"candidate_id_mismatch"):
            jf.validate_staged_provenance(self.row,self.jid,self.sid,corrupt)

    def test_private_stage_uses_original_publisher_db_without_overwrite(self):
        with patch.object(jf.stage,"STAGED",self.stage_dir), \
             patch.object(jf.stage,"STAGE_DB",self.stage_db), \
             patch.object(jf.publisher,"STAGED",self.stage_dir), \
             patch.object(jf.publisher,"STAGE_DB",self.stage_db):
            with jf.stage.stage_db() as db:
                r=jf.preserve(self.row,self.candidate,self.raw,self.metrics,db)
                self.assertEqual(r["status"],"staged_not_published")
                self.assertEqual(len(list(self.stage_dir.iterdir())),1)
                stage_file,data,info=jf.publisher.read_staging(self.jid,self.sid)
                self.assertEqual(data,self.raw)
                self.assertEqual(info["source_remote_provider"],"subbuzz")
                self.assertEqual(jf.publisher.source_label(self.jid,self.sid),"jellyfin")
                self.assertEqual(stage_file.stat().st_mode&0o777,0o600)
                again=jf.preserve(self.row,self.candidate,self.raw,self.metrics,db)
                self.assertEqual(again["status"],"already_staged")
                self.assertEqual(db.execute("SELECT count(*) FROM staged").fetchone()[0],1)
                with self.assertRaisesRegex(RuntimeError,"conflicting_existing_private_stage"):
                    jf.preserve(self.row,self.candidate,self.raw+b"tamper",self.metrics,db)
                self.assertEqual(stage_file.read_bytes(),self.raw)

    def test_no_false_identity_or_missing_year(self):
        movie={"kind":"Movie","title":"Bride of Chucky","year":1998,
               "status":"ready_ja_search","jellyfin_id":self.jid}
        candidate=dict(self.candidate,Name="Bride.of.Re-Animator.1990.ja")
        with self.assertRaisesRegex(RuntimeError,"exact_Jellyfin_media"):
            jf.stage_metadata(movie,candidate,self.sid,self.hash,
                              self.raw,1200,self.qa)
        self.assertFalse(jf.probe.relevant(movie,
            dict(self.candidate,Name="Bride.of.Chucky.2008.ja")))


if __name__=="__main__":
    unittest.main()
