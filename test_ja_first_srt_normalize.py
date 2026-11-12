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
        raw=("1\n00:00:01,000 --> 00:00:03,000\nこんにちは\n"
             "2\n00:00:04,000 --> 00:00:06,000\nもう一度").encode("utf-8")
        with self.assertRaisesRegex(RuntimeError,
                                    "staged_srt_multiple_timestamps_per_block"):
            norm.normalize(raw,expected_timestamps=2)

    def test_missing_blank_line_between_complete_cues_preserves_green_room_dialogue(self):
        # Actual host block 1233 has 2 standalone stamps and real JP
        # dialogue but only one SRT blank-line boundary.
        sample=(
            "1234\\n01:21:22,245 --> 01:21:23,444\\n投げ捨てろ\\n"
            "01:22:22,604 --> 01:22:24,104\\n\\\"犬に注意\\\"\\n"
        ).encode("utf-8")
        out,report=norm.normalize(sample,expected_timestamps=2)
        self.assertEqual(report["merged_blocks_repaired"],1)
        self.assertEqual(report["merged_cues_recovered"],1)
        self.assertEqual(report["retained_dialogue_cues"],2)
        self.assertIn("投げ捨てろ".encode(),out)
        self.assertIn('"犬に注意"'.encode(),out)
        self.assertIn(b"1\\n01:21:22,245",out)
        self.assertIn(b"2\\n01:22:22,604",out)
        self.assertEqual(sample.count("投げ捨てろ".encode()),
                         out.count("投げ捨てろ".encode()))
        self.assertEqual(sample.count("犬に注意".encode()),
                         out.count("犬に注意".encode()))

    def test_multiple_complete_merged_srt_blocks_all_repaired(self):
        raw=(cue(1,"00:00:01,000","00:00:02,000","始まり")+
             ("2\\n00:00:03,000 --> 00:00:04,000\\n待って\\n"
              "00:00:05,000 --> 00:00:06,000\\n行こう\\n\\n"
              "4\\n00:00:07,000 --> 00:00:08,000\\nはい").encode())
        out,report=norm.normalize(raw,expected_timestamps=4)
        self.assertEqual(report["merged_blocks_repaired"],1)
        self.assertEqual(report["retained_dialogue_cues"],4)
        for line in ("始まり","待って","行こう","はい"):
            self.assertEqual(raw.count(line.encode()),out.count(line.encode()))

    def test_ambiguous_or_missing_dialogue_merged_stays_held(self):
        missing=(
            "1\\n00:00:01,000 --> 00:00:02,000\\n"
            "00:00:03,000 --> 00:00:04,000\\n最後").encode()
        with self.assertRaisesRegex(RuntimeError,"merged_block_missing_dialogue"):
            norm.normalize(missing,expected_timestamps=2)
        numbered=(
            "1\\n00:00:01,000 --> 00:00:02,000\\nこんにちは\\n"
            "2\\n00:00:03,000 --> 00:00:04,000\\n最後").encode()
        with self.assertRaisesRegex(RuntimeError,"merged_block_ambiguous_index"):
            norm.normalize(numbered,expected_timestamps=2)

    def test_out_of_order_detected_with_exact_cue_numbers_and_no_mutation(self):
        source=(cue(1,"00:00:10,000","00:00:11,000","はじめ")+
                cue(2,"00:00:30,000","00:00:31,000","次の場面")+
                cue(3,"00:00:20,000","00:00:21,000","その前")+
                cue(4,"00:00:40,000","00:00:41,000","最後"))
        result=norm.inspect_timestamp_reversals(source)
        self.assertEqual(result["timestamp_reversals"],1)
        self.assertEqual(result["examples"][0]["prior_block"],2)
        self.assertEqual(result["examples"][0]["later_block"],3)
        self.assertEqual(result["examples"][0]["backward_jump_seconds"],10)
        self.assertIn("その前",result["examples"][0]["later_text"])
        with self.assertRaisesRegex(RuntimeError,"staged_srt_cue_order_invalid"):
            norm.normalize(source,expected_timestamps=4)

    def test_strict_first_cue_release_note_only_excluded_when_requested(self):
        note="「1：50：50の動画に合わせていますが、若干のズレあり」"
        raw=(cue(1,"00:00:12,849","00:00:19,849",note)+
             cue(2,"00:01:00,000","00:01:02,000","私はここにいる")+
             cue(3,"00:02:00,000","00:02:02,000","もう帰ろう"))
        before,report=norm.normalize(raw,expected_timestamps=3)
        self.assertIs(before,raw)
        self.assertEqual(report["technical_release_notes_excluded"],0)
        derived,changed=norm.normalize(raw,expected_timestamps=3,
                                        trial_release_note=True)
        self.assertEqual(changed["technical_release_notes_excluded"],1)
        self.assertEqual(changed["retained_dialogue_cues"],2)
        self.assertNotIn(note.encode(),derived)
        self.assertIn("私はここにいる".encode(),derived)
        self.assertIn("もう帰ろう".encode(),derived)
        self.assertEqual(raw.count("私はここにいる".encode()),1)

    def test_spoken_dialogue_with_duration_stays(self):
        raw=(cue(1,"00:00:10,000","00:00:12,000",
                 "1：50：50の映画を昨日見たよ")+
             cue(2,"00:00:15,000","00:00:16,000","はい"))
        output,record=norm.normalize(raw,expected_timestamps=2,
                                     trial_release_note=True)
        self.assertIs(output,raw)
        self.assertEqual(record["technical_release_notes_excluded"],0)

    def test_single_small_reversal_swaps_entire_time_text_pairs_trial_only(self):
        raw=(cue(1,"00:00:10,000","00:00:11,000","始めます")+
             cue(2,"00:12:58,028","00:12:59,900","いいね")+
             cue(3,"00:12:56,401","00:12:57,200","頭の回路が変なの")+
             cue(4,"00:13:02,000","00:13:04,000","続けて"))
        with self.assertRaisesRegex(RuntimeError,"cue_order_invalid"):
            norm.normalize(raw,expected_timestamps=4)
        modified,info=norm.normalize(raw,expected_timestamps=4,
                                     trial_local_swap=True)
        self.assertEqual(info["local_timestamp_swaps"],
                         [{"original_cues":[2,3],"jump_ms":1627}])
        self.assertEqual(info["retained_dialogue_cues"],4)
        self.assertLess(modified.index("頭の回路が変なの".encode()),
                        modified.index("いいね".encode()))
        for text in ("始めます","頭の回路が変なの","いいね","続けて"):
            self.assertEqual(raw.count(text.encode()),modified.count(text.encode()))

    def test_large_or_nonadjacent_reversal_remains_held_in_trial(self):
        raw=(cue(1,"00:00:10,000","00:00:11,000","あ")+
             cue(2,"00:00:30,000","00:00:31,000","い")+
             cue(3,"00:00:20,000","00:00:21,000","う")+
             cue(4,"00:00:40,000","00:00:41,000","え"))
        with self.assertRaisesRegex(RuntimeError,"cue_order_invalid"):
            norm.normalize(raw,expected_timestamps=4,trial_local_swap=True)
        # A too-small swap cannot sort this entire sequence either.
        nested=(cue(1,"00:00:10,000","00:00:11,000","あ")+
                cue(2,"00:00:11,800","00:00:13,000","い")+
                cue(3,"00:00:11,000","00:00:12,000","う")+
                cue(4,"00:00:11,400","00:00:14,000","え"))
        with self.assertRaisesRegex(RuntimeError,"cue_order_invalid"):
            norm.normalize(nested,expected_timestamps=4,
                           trial_local_swap=True)

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
