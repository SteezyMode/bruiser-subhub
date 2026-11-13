"""The SubDL archive parser and publisher must agree on accepted SRT clocks.

All fixtures use synthetic Japanese dialogue and fake movie identities.
No provider, media, persistent DB or subtitle output is accessed.
"""
from io import BytesIO
import unittest
import zipfile

from tools import ja_first_srt_normalize as structure
from tools import ja_first_publish_staged as publisher
from tools import ja_first_stage_subdl as subdl


def japanese_srt(clock_style="canonical"):
    lines=[]
    for i in range(100):
        start=i*4
        end=start+2
        def stamp(sec):
            m,s=divmod(sec,60)
            if clock_style=="unicode_horizontal_space":
                return f"00:{m:02}:{s:02}.00"
            return f"00:{m:02}:{s:02},000"
        arrow=("\u00a0-->\u00a0" if clock_style=="unicode_horizontal_space"
               else " --> ")
        lines.append(
            f"{i+1}\n{stamp(start)}{arrow}{stamp(end)}\n"
            f"日本語の字幕を保存します。行番号{i+1}\n")
    return "\n".join(lines).encode("utf-8")


class SrtPipelineContractTests(unittest.TestCase):
    def test_validated_unicode_spacing_and_fraction_canonicalized_for_publisher(self):
        raw=japanese_srt("unicode_horizontal_space")
        new,report=structure.normalize(raw,trial_local_swap=True)
        self.assertEqual(report["source_timestamp_cues"],100)
        self.assertEqual(report["retained_dialogue_cues"],100)
        self.assertEqual(report["timestamp_formats_normalized"],100)
        self.assertEqual(new.count("日本語の字幕を保存します".encode()),100)
        self.assertIn(b"00:00:00,000 --> 00:00:02,000",new)
        self.assertNotIn("\u00a0".encode(),new)
        qa=publisher.validate_srt(new,1200.0)
        self.assertEqual(qa["cues"],100)

    def test_subdl_archive_uses_same_canonicalization(self):
        zip_bytes=BytesIO()
        with zipfile.ZipFile(zip_bytes,"w") as z:
            z.writestr("Example Film (Japanese).srt",
                       japanese_srt("unicode_horizontal_space"))
            z.writestr("Example Film (Japanese Forced).srt",b"forced")
        row={"kind":"Movie","title":"Example Film","year":2025}
        working,qa,name=subdl.archive_srt(
            zip_bytes.getvalue(),row,{},1200.0)
        self.assertEqual(name,"Example Film (Japanese).srt")
        self.assertEqual(qa["cues"],100)
        self.assertEqual(qa["structural_repair"]["timestamp_formats_normalized"],100)
        self.assertEqual(publisher.validate_srt(working,1200.0)["cues"],100)

    def test_normal_srt_no_unncessary_rewrite(self):
        raw=japanese_srt()
        new,report=structure.normalize(raw)
        self.assertEqual(new,raw)
        self.assertEqual(report["timestamp_formats_normalized"],0)
        self.assertFalse(report["structural_repair"])

    def test_missing_clock_is_still_held(self):
        raw=japanese_srt().replace(
            b"00:00:12,000 --> 00:00:14,000",b"bad missing timestamp",1)
        with self.assertRaises(RuntimeError):
            structure.normalize(raw)
        with self.assertRaises(RuntimeError):
            publisher.validate_srt(raw,1200.0)


if __name__=="__main__":
    unittest.main()
