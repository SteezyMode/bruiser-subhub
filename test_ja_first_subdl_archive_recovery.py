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

    def test_lossless_separator_repair_accepts_real_japanese_subdl_zip(self):
        # Large enough for real SubHub Japanese density/full-movie checks.
        cues=[]
        for i in range(1,81):
            start=i*12000
            finish=start+1800
            def clock(ms):
                h,ms=divmod(ms,3600000)
                m,ms=divmod(ms,60000)
                sec,ms=divmod(ms,1000)
                return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
            cues.append(f"{i}\n{clock(start)} --> {clock(finish)}\n"
                        f"日本語の字幕をそのまま残す {i}")
        raw=("\n\n".join(cues[:10])+"\n\n"+
             "\n".join(cues[10:12])+"\n\n"+
             "\n\n".join(cues[12:])+"\n").encode("utf-8")
        blob=archive({"Double.Blind.2023.1080p.ja.srt":raw})
        # The old validator incorrectly COUNTS this merged block as one
        # valid cue, swallowing the second timestamp into dialogue. The new
        # normalizer restores the 80th clock before validation.
        from tools import ja_first_publish_staged as gate
        self.assertEqual(gate.validate_srt(raw,1100.0)["cues"],79)
        text,qa,member=subdl.archive_srt(
            blob,self.row,self.candidate,1100.0)
        self.assertEqual(member,"Double.Blind.2023.1080p.ja.srt")
        self.assertEqual(qa["cues"],80)
        self.assertEqual(qa["structural_repair"]["merged_blocks_repaired"],1)
        self.assertEqual(qa["structural_repair"]["retained_dialogue_cues"],80)
        self.assertEqual(
            qa["original_zip_member_sha256"],
            __import__("hashlib").sha256(raw).hexdigest())
        self.assertEqual(raw.count("日本語の字幕をそのまま残す".encode()),
                         text.count("日本語の字幕をそのまま残す".encode()))

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
