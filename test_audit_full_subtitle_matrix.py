"""Bilingual subtitle matrix regression tests; all offline."""
import tempfile
from pathlib import Path
import unittest
from tools import audit_full_subtitle_matrix as mat

class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.video = Path(self.work.name) / "Film.mkv"
        self.video.write_bytes(b"sample")
    def scan(self, subtitles, extra=None):
        item = {"MediaStreams": subtitles}
        return mat.scan_one(self.video, item, {}, extra)
    def test_both_languages(self):
        subs = [{"Type":"Subtitle","Language":"eng","Codec":"subrip"},
                {"Type":"Subtitle","Language":"jpn","Codec":"ass"}]
        r = self.scan(subs)
        self.assertEqual(r["category"], "both")
        self.assertTrue(r["english_text"])
        self.assertTrue(r["japanese_text"])
    def test_each_language_and_neither(self):
        en = [{"Type":"Subtitle","Language":"en","Codec":"subrip"}]
        ja = [{"Type":"Subtitle","Language":"ja","Codec":"ass"}]
        self.assertEqual(self.scan(en)["category"], "english_only")
        self.assertEqual(self.scan(ja)["category"], "japanese_only")
        self.assertEqual(self.scan([])["category"], "neither")
    def test_existing_japanese_sidecar_counts_with_english(self):
        (self.video.parent/"Film.ja.PLaMo8B.srt").write_text("example")
        r = self.scan([{"Type":"Subtitle","Language":"eng","Codec":"srt"}])
        self.assertEqual(r["category"], "both")
    def test_forced_ja_does_not_count_as_full_translation(self):
        subs=[{"Type":"Subtitle","Language":"eng","Codec":"srt"},
              {"Type":"Subtitle","Language":"jpn","Codec":"srt","IsForced":True}]
        self.assertEqual(self.scan(subs)["category"], "english_only")
    def test_stale_jellyfin_english_not_confirmed(self):
        en=[{"Type":"Subtitle","Language":"eng","Codec":"srt"}]
        result=self.scan(en, {"ffprobe_status":"jellyfin_track_not_in_video"})
        self.assertEqual(result["category"], "unknown")
        self.assertFalse(result["english_subtitles"])
    def test_bitmap_english_counts_as_subtitle_but_not_text(self):
        subs=[{"Type":"Subtitle","Language":"eng","Codec":"hdmv_pgs_subtitle"}]
        result=self.scan(subs)
        self.assertEqual(result["category"], "english_only")
        self.assertTrue(result["english_bitmap"])
        self.assertFalse(result["english_text"])

if __name__ == "__main__":
    unittest.main()
