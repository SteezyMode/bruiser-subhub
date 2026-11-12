"""Offline tests for pure, byte-preserving Japanese SRT structural repair."""
import unittest
from tools import ja_first_srt_normalize as norm


def cue(n,start,end,text):
    return (f"{n}\n{start} --> {end}\n{text}\n\n").encode("utf-8")


class StructuralNormalizationTests(unittest.TestCase):
    def test_empty_last_cue_is_only_removed(self):
        raw=(cue(1,"00:00:01,000","00:00:03,000","女の子")+
             cue(2,"00:00:04,000","00:00:06,000","また")+
             b"3\n00:00:07,000 --> 00:00:09,000\n")
        saved=raw[:]
        out,report=norm.normalize(raw,expected_timestamps=3)
        self.assertEqual(report["source_timestamp_cues"],3)
        self.assertEqual(report["empty_cues_removed"],1)
        self.assertEqual(report["retained_dialogue_cues"],2)
        self.assertIn("女の子".encode(),out)
        self.assertIn("また".encode(),out)
        self.assertNotIn(b"00:00:07",out)
        self.assertEqual(raw,saved)

    def test_empty_mid_cues_and_leading_newline_safely_repaired(self):
        raw=(cue(1,"00:00:01,000","00:00:03,000","父さん")+
             b"2\n00:00:04,000 --> 00:00:06,000\n\n\n"+
             "\n3\n00:00:07,000 --> 00:00:09,000\n大丈夫".encode("utf-8"))
        out,report=norm.normalize(raw,expected_timestamps=3)
        self.assertEqual(report["empty_cues_removed"],1)
        self.assertEqual(report["retained_dialogue_cues"],2)
        self.assertIn("父さん".encode(),out)
        self.assertIn("大丈夫".encode(),out)

    def test_three_sub_control_bytes_only_are_removed(self):
        raw=(cue(1,"00:00:01,000","00:00:03,000","千尋\x1a")+
             cue(2,"00:00:04,000","00:00:06,000","ハク\x1a")+
             cue(3,"00:00:07,000","00:00:09,000","あ\x1a"))
        out,report=norm.normalize(raw,expected_timestamps=3)
        self.assertEqual(report["control_characters_removed"],3)
        self.assertEqual(report["retained_dialogue_cues"],3)
        self.assertEqual(out.count(b"\x1a"),0)
        for name in ("千尋","ハク","あ"):
            self.assertIn(name.encode(),out)

    def test_valid_srt_exactly_preserved(self):
        raw=(cue(1,"00:00:01,000","00:00:03,000","まだ")+
             cue(2,"00:00:04,000","00:00:06,000","だめ"))
        out,report=norm.normalize(raw,expected_timestamps=2)
        self.assertIs(out,raw)
        self.assertFalse(report["structural_repair"])

    def test_nonempty_orphan_text_is_not_dropped(self):
        raw=(cue(1,"00:00:01,000","00:00:03,000","こんにちは")+
             b"MISSING TIMESTAMP\nthis text cannot disappear")
        with self.assertRaisesRegex(RuntimeError,"staged_srt_block_malformed"):
            norm.normalize(raw,expected_timestamps=1)

    def test_merged_cues_are_not_silently_discarded(self):
        raw=(b"1\n00:00:01,000 --> 00:00:03,000\nこんにちは\n"
             b"2\n00:00:04,000 --> 00:00:06,000\nもう一度")
        with self.assertRaisesRegex(RuntimeError,
                                    "staged_srt_multiple_timestamps_per_block"):
            norm.normalize(raw,expected_timestamps=2)

    def test_invalid_clock_and_truncated_bytes_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError,"invalid_staged_srt_clock"):
            norm.normalize(cue(1,"00:99:01,000","00:99:03,000","はい"))
        with self.assertRaisesRegex(RuntimeError,
                                    "staged_srt_timestamps_mismatch"):
            norm.normalize(cue(1,"00:00:01,000","00:00:03,000","はい"),
                           expected_timestamps=12)
        with self.assertRaisesRegex(RuntimeError,"staged_srt_not_utf8"):
            norm.normalize(b"\xff"*400)


if __name__=="__main__":
    unittest.main()
