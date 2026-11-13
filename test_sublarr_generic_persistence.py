"""Generic Sublarr stages are private, create-only and compatible with publisher."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools import ja_first_stage_sublarr as generic
from tools import ja_first_publish_staged as publisher
from tools import subhub_download_ledger as ledger


def row():
    return {"jellyfin_id":"a"*32,"kind":"Movie","status":"ready_ja_search",
            "title":"Black Christmas","year":1974,
            "host_path":"/mnt/2TB/Plex Expansion/Movies/Horror/Black Christmas.mkv"}


def candidate():
    return {"provider":"subf2m","subtitle_id":"subf2m-abcdefg",
            "filename":"Black.Christmas.1974.Japanese.srt",
            "release_info":"Black.Christmas.1974.BluRay",
            "language":"ja","format":"srt","kind":"full","forced":False}


class PersistenceTests(unittest.TestCase):
    def test_stage_is_create_only_and_accepted_by_publisher_without_media_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            root.chmod(0o700)
            staged=root/"staged"
            staged.mkdir(mode=0o700)
            dbpath=root/"stage.sqlite3"
            connection=sqlite3.connect(dbpath)
            connection.execute("""
                CREATE TABLE staged (
                    jellyfin_id TEXT NOT NULL,
                    subtitle_id TEXT NOT NULL,
                    host_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    staged_at INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    PRIMARY KEY (jellyfin_id,subtitle_id))""")
            connection.commit()
            connection.close()
            dbpath.chmod(0o600)
            def open_db():
                return sqlite3.connect(dbpath)
            r=row()
            c=candidate()
            raw=b"1\n00:00:01,000 --> 00:00:02,000\n" + "日本語です".encode()
            qa={"cues":1,"japanese_characters":6,"japanese_cue_fraction":1.0}
            with patch.object(generic.stage,"STAGED",staged), \
                 patch.object(generic.stage,"private_root"), \
                 patch.object(generic.stage,"stage_db",side_effect=open_db), \
                 patch.object(generic,"source_candidates",return_value=[c]), \
                 patch.object(publisher,"STAGED",staged), \
                 patch.object(publisher,"STAGE_DB",dbpath):
                sid=generic.preserve(r,c,raw,1200.0,qa)
                self.assertEqual(generic.preserve(r,c,raw,1200.0,qa),sid)
                name=r["jellyfin_id"]+".sublarr."+sid+".ja.srt"
                self.assertEqual((staged/name).read_bytes(),raw)
                self.assertEqual((staged/name).stat().st_mode & 0o777,0o600)
                path,data,metrics=publisher.read_staging(r["jellyfin_id"],sid)
                self.assertEqual(path,staged/name)
                self.assertEqual(data,raw)
                self.assertEqual(metrics["provider"],"sublarr")
                self.assertEqual(metrics["source_remote_provider"],"subf2m")
                with self.assertRaisesRegex(RuntimeError,"conflicting_existing_generic_stage"):
                    generic.preserve(r,c,b"different-content",1200.0,qa)
                self.assertEqual((staged/name).read_bytes(),raw)
            with sqlite3.connect(dbpath) as db:
                count=db.execute("SELECT COUNT(*) FROM staged").fetchone()[0]
            self.assertEqual(count,1)

    def test_generic_downloads_are_attributed_by_actual_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            root.chmod(0o700)
            path=root/"ledger.sqlite3"
            event=ledger.begin("subf2m","sublarr_provider_manager",path=path)
            ledger.finish(event,"downloaded",byte_count=512,path=path)
            report=ledger.summary(path=path)
            day=report["today"]
            self.assertEqual(day["providers"]["subf2m"]["downloaded"],1)
            with self.assertRaisesRegex(ValueError,"invalid_provider_or_route"):
                ledger.begin("subf2m","jellyfin_native",path=path)


if __name__=="__main__":
    unittest.main()
