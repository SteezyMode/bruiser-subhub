"""Offline read-only opening subtitle annotation census regressions."""
import unittest

from tools import subhub_opening_note_audit as audit


def cue(index,start,end,text):
    return (f"{index}\n{start} --> {end}\n{text}\n\n").encode("utf-8")


class OpeningMetadataTests(unittest.TestCase):
    def test_golden_glove_note_matches_strict_first_cue_only(self):
        raw=(cue(1,"00:00:12,849","00:00:19,849",
                 "「1：50：50の動画に合わせていますが、若干のズレあり」")+
             cue(2,"00:00:45,000","00:00:47,000","何をしている？"))
        result=audit.opening_candidates(raw)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["kind"],"recognized_first_cue_timing_note")
        self.assertEqual(result[0]["cue"],1)

    def test_translator_credit_is_only_flagged_not_dropped(self):
        raw=(cue(1,"00:00:07,000","00:00:09,000","字幕翻訳：田中")+
             cue(2,"00:00:15,000","00:00:17,000","こんにちは"))
        result=audit.opening_candidates(raw)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["kind"],"possible_credit_needs_review")

    def test_spoken_subtitle_words_are_not_credited_to_translator(self):
        raw=(cue(1,"00:00:09,000","00:00:11,000","字幕って読めますか？")+
             cue(2,"00:00:12,000","00:00:13,000","そうですね"))
        self.assertEqual(audit.opening_candidates(raw),[])

    def test_ending_translation_credit_not_an_opening_problem(self):
        raw=(cue(1,"00:00:09,000","00:00:11,000","こんにちは")+
             cue(2,"00:00:12,000","00:00:13,000","そうですね")+
             cue(3,"02:00:09,000","02:00:11,000","翻訳：永井 歌子"))
        self.assertEqual(audit.opening_candidates(raw),[])


if __name__=="__main__":
    unittest.main()
