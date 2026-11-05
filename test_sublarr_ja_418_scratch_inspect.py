"""Offline regression tests: safe S22E02 Japanese candidate selection and QA."""
import unittest
from tools import sublarr_ja_418_scratch_inspect as probe


class TestJapaneseScratchInspect(unittest.TestCase):
    def test_exact_language_provider_dialogue_only(self):
        bad=[
            dict(provider_name="subdl",language="ja",subtitle_id="100",score=290),
            dict(provider_name="opensubtitles",language="en",subtitle_id="1",score=400),
            dict(provider_name="opensubtitles",language="ja",subtitle_id="2",score=310,forced=True),
            dict(provider_name="opensubtitles",language="ja",subtitle_id="3",score=300,kind="signs"),
            dict(provider_name="opensubtitles",language="ja",subtitle_id="4",score=150),
        ]
        self.assertIsNone(probe.select_candidate(bad))
        valid=dict(provider_name="opensubtitles",language="ja",subtitle_id="5",score=240,
                   filename="American.Dad.S22E02-FENiX.ja.ass",kind="full",forced=False)
        self.assertEqual(probe.select_candidate(bad+[valid]),valid)

    def test_same_release_prioritized_over_weak_filename_match(self):
        a=dict(provider_name="opensubtitles",language="ja",subtitle_id="strong",score=250,
               filename="Other.Release.S22E02.ja.srt")
        b=dict(provider_name="opensubtitles",language="ja",subtitle_id="match",score=240,
               filename="American.Dad.S22E02.720p.x264-FENiX.ja.ass")
        self.assertEqual(probe.select_candidate([a,b]),b)

    def test_format_detection(self):
        self.assertEqual(probe.subtitle_kind(
            b"[Script Info]\nTitle: Test\n[Events]\nFormat: Start, End, Text\n"),".ass")
        self.assertEqual(probe.subtitle_kind(
            b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"),".srt")
        self.assertEqual(probe.subtitle_kind(b"WEBVTT\n\n00:01.000 --> 00:02.000\n"),".vtt")
        self.assertEqual(probe.subtitle_kind(b"no header and no cue","invalid"),"")

    def test_japanese_screen_is_not_semantic_quality_score(self):
        cues=[
            {"start":1000,"end":3000,"text":"彼女はここにいる"},
            {"start":3100,"end":6000,"text":"Hello from English"},
            {"start":6100,"end":9000,"text":"おはよう"},
        ]
        x=probe.summarize_cues(cues,25.0)
        self.assertEqual(x["dialogue_event_count"],3)
        self.assertEqual(x["japanese_script_event_count"],2)
        self.assertEqual(x["out_of_video_events"],0)
        self.assertEqual(x["nonpositive_duration_events"],0)

    def test_empty_cues_do_not_divide_by_zero(self):
        x=probe.summarize_cues([],None)
        self.assertEqual(x["dialogue_event_count"],0)
        self.assertIsNone(x["japanese_script_event_fraction"])
        self.assertEqual(x["timeline_sample_seconds"],[])


if __name__=="__main__":
    unittest.main()
