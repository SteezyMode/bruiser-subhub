"""Stable bad ZIP receipts skip duplicate work, not new parser releases."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import ja_first_stage_subdl as subdl
from tools import ja_first_candidate_progress as progress


def row():
    return {"jellyfin_id":"a"*32,
            "host_path":"/mnt/2TB/Plex Expansion/Movies/Horror/Sample.mkv"}


def candidate():
    return {"subtitle_id":"some-subdl-remote-id","provider":"subdl"}


class CachedZipFailureTests(unittest.TestCase):
    def test_bad_cached_release_skipped_with_matching_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"cached.zip"
            path.write_bytes(b"some provider bytes")
            path.chmod(0o600)
            with patch.object(subdl,"cached_zip_path",return_value=path), \
                 patch.object(subdl,"numeric_id",return_value=("11234","idsha")), \
                 patch.object(subdl.progress,"fingerprint",return_value="f"*64) as fp, \
                 patch.object(subdl.progress,"known",
                              return_value="subdl_archive_srt_rejected:bad_clock") as known:
                result=subdl.known_rejected_cached(row(),candidate())
            self.assertIn("bad_clock",result)
            self.assertEqual(fp.call_args.args[-1],"subdl-stage")
            self.assertEqual(known.call_args.args[2],"subdl-stage")

    def test_cache_not_present_does_not_create_a_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"missing.zip"
            with patch.object(subdl,"cached_zip_path",return_value=path), \
                 patch.object(subdl.progress,"known") as known:
                self.assertIsNone(subdl.known_rejected_cached(row(),candidate()))
                known.assert_not_called()

    def test_only_stable_content_errors_are_remembered(self):
        with patch.object(subdl,"numeric_id",return_value=("11234","idsha")), \
             patch.object(subdl.progress,"fingerprint",return_value="f"*64), \
             patch.object(subdl.progress,"remember") as remember:
            subdl.remember_cached_rejection(
                row(),candidate(),b"zip",RuntimeError(
                    "subdl_archive_srt_rejected:unparseable_srt_timestamp"))
            remember.assert_called_once()
            remember.reset_mock()
            subdl.remember_cached_rejection(
                row(),candidate(),b"zip",RuntimeError("ffprobe_failed"))
            remember.assert_not_called()

    def test_versioned_implementation_includes_parser(self):
        self.assertIn("ja_first_srt_normalize.py",
                      progress.MODULES["subdl-stage"])
        self.assertIn("ja_first_stage_subdl.py",
                      progress.MODULES["subdl-stage"])


if __name__=="__main__":
    unittest.main()
