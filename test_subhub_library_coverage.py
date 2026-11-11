"""No-provider, no-GPU tests for global JA subtitle coverage accounting."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from tools import subhub_library_coverage as coverage


class LibraryCoverageTests(unittest.TestCase):
    def test_separates_movies_episodes_missing_and_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            a=root/"A.mkv"; b=root/"B.mkv"; c=root/"C.mkv"; d=root/"D.mkv"
            for p in (a,b,c,d):p.write_bytes(b"video")
            (root/"B.jpn.srt").write_text("Japanese")
            (root/"C.ja.forced.srt").write_text("signs only")
            rows=[
                {"kind":"Movie","status":"existing_japanese_subtitle","host_path":str(a)},
                {"kind":"Movie","status":"ready_ja_search","host_path":str(b)},
                {"kind":"Episode","status":"ready_ja_search","host_path":str(c)},
                {"kind":"Episode","status":"review_missing_media_streams","host_path":str(d)},
                {"kind":"Episode","status":"japanese_audio","host_path":str(c)},
            ]
            r=coverage.summarize(rows,generated_utc="2026-11-11T01:00:00+00:00",now=1)
            self.assertEqual(r["total"],5)
            self.assertEqual(r["present"],2)
            self.assertEqual(r["missing"],2)
            self.assertEqual(r["unverified"],1)
            self.assertEqual(r["japanese_audio_only"],1)
            self.assertEqual(r["subtitle_sidecars_found_since_snapshot"],1)
            self.assertEqual(r["by_kind"]["Movie"]["present"],2)

    def test_sidecars_never_override_forced_or_other_media_and_no_fake_live_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            video=root/"Movie.2026.mkv"
            video.write_bytes(b"clip")
            (root/"Movie.2026.ja.forced.srt").write_text("sign")
            (root/"Other.Movie.ja.srt").write_text("unrelated")
            result=coverage.summarize([
                {"kind":"Movie","status":"ready_ja_search","host_path":str(video)}
            ],now=1)
            self.assertEqual((result["present"],result["missing"]),(0,1))
            self.assertIn("snapshot",result["note"])

    def test_manifest_cache_and_existing_files_are_not_mutated(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            video=root/"Film.mkv";video.write_bytes(b"clip")
            manifest=root/"ja-intake-20261111T090000Z.json"
            manifest.write_text(json.dumps({
                "schema":1,"generated_utc":"2026-11-11T00:00:00+00:00",
                "items":[{"kind":"Movie","status":"ready_ja_search","host_path":str(video)}]}))
            manifest.chmod(0o600)
            with patch.dict(coverage._CACHE,{"signature":None,"expires":0.0,"result":None}):
                first=coverage.pulse(root,ttl=0)
                self.assertEqual(first["missing"],1)
                (root/"Film.ja.srt").write_text("Japanese")
                second=coverage.pulse(root,ttl=0)
                self.assertEqual(second["present"],1)
                self.assertEqual(second["missing"],0)
                self.assertEqual(video.read_bytes(),b"clip")

if __name__=="__main__":
    unittest.main()
