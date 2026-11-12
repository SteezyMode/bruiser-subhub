"""SubDL ZIP handling: bounded private cache and actionable read-only failures."""
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile,ZIP_DEFLATED

from tools import ja_first_stage_subdl as subdl


def archive(files):
    stream=BytesIO()
    with ZipFile(stream,"w",ZIP_DEFLATED) as z:
        for name,data in files.items():
            z.writestr(name,data)
    return stream.getvalue()


class SubdlArchiveRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.row={"kind":"Movie","title":"Double Blind","year":2024}
        self.candidate={"provider":"subdl","subtitle_id":"3746725-8668631",
                        "language":"ja",
                        "filename":"Double.Blind.2023.1080p.ja.srt"}

    def test_no_srt_members_distinguished_from_bad_dialogue(self):
        blob=archive({"some.release.ass":"[Events]\nDialogue: data"})
        with self.assertRaisesRegex(RuntimeError,"subdl_archive_no_srt_members"):
            subdl.archive_srt(blob,self.row,self.candidate,7000.0)

    def test_multiple_srt_members_with_wrong_film_held(self):
        blob=archive({
            "Some.Other.Movie.2024.ja.srt":b"hello",
            "Wrong.Series.2024.ja.srt":b"hello",
        })
        with self.assertRaisesRegex(RuntimeError,
                                    "subdl_archive_no_matching_srt_member"):
            subdl.archive_srt(blob,self.row,self.candidate,7000.0)

    def test_single_srt_with_invalid_japanese_content_is_not_accepted(self):
        blob=archive({"anything.srt":b"1\n00:00:01,000 --> 00:00:02,000\nhi\n"})
        with self.assertRaisesRegex(RuntimeError,
                                    "subdl_archive_srt_rejected:"):
            subdl.archive_srt(blob,self.row,self.candidate,7000.0)

    def test_existing_zip_cached_even_if_later_content_validation_fails(self):
        blob=archive({"anything.srt":b"bad dialogue not yet verified"})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"staged"
            with patch.object(subdl.stage,"STAGED",root), \
                 patch.object(subdl,"download",return_value=blob) as get:
                first=subdl.cached_archive(self.candidate)
                second=subdl.cached_archive(self.candidate)
            self.assertEqual(first,second)
            get.assert_called_once()
            cached=list((root/"subdl-source-zips").glob("*.zip"))
            self.assertEqual(len(cached),1)
            self.assertEqual(cached[0].read_bytes(),blob)
            self.assertEqual(cached[0].stat().st_mode&0o077,0)
            self.assertEqual(cached[0].parent.stat().st_mode&0o077,0)

    def test_cached_symlink_is_refused_without_network_request(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"staged"
            folder=root/"subdl-source-zips"
            folder.mkdir(parents=True,mode=0o700)
            # tempfile parents can inherit mode 0755: the production cache
            # correctly rejects that, but this test must model a safe stage.
            root.chmod(0o700)
            _,digest=subdl.numeric_id(self.candidate["subtitle_id"])
            (folder/(digest+".zip")).symlink_to(Path(d)/"outside")
            with patch.object(subdl.stage,"STAGED",root), \
                 patch.object(subdl,"download") as get:
                with self.assertRaisesRegex(RuntimeError,
                                            "unsafe_private_subdl_archive_symlink"):
                    subdl.cached_archive(self.candidate)
            get.assert_not_called()


if __name__=="__main__":
    unittest.main()
