"""Regression tests for isolated small-PLaMo comparison protocol."""
import tempfile
import unittest
from pathlib import Path
from tools import plamo3_small_ab as trial


class PlamoSmallTrialTests(unittest.TestCase):
    def test_native_pfml3_prompt_and_stops(self):
        p=trial.pfml3("Not a chance.")
        self.assertTrue(p.startswith("<|plamo:tag|>dataset<|plamo:msg|>translation"))
        self.assertIn("<|plamo:tag|>input<|plamo:msg|>Not a chance.",p)
        self.assertTrue(p.endswith("<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja<|plamo:msg|>"))
        self.assertEqual(trial.STOP,["<|plamo:tag|>","<|plamo:bos|>"])
        with self.assertRaises(ValueError):
            trial.pfml3("  ")

    def test_stable_original_english_demo_and_timecodes(self):
        data=trial.samples()
        self.assertEqual(len(data),16)
        self.assertEqual(data[0]["start"],"00:00:00,000")
        self.assertEqual(data[-1]["start"],"00:01:30,000")
        srt=trial.format_srt(data,"english")
        self.assertEqual(trial.parse_srt(srt),data)
        self.assertEqual(trial.parse_srt(srt,5),data[:5])

    def test_incomplete_or_invalid_srt_held(self):
        for wrong in ("", "hello", "1\nnot_a_timestamp\nhello",
                      "1\n00:00:00,000 --> 00:00:01,000\n"):
            with self.assertRaises(ValueError):
                trial.parse_srt(wrong)
        first=trial.format_srt(trial.samples()[:1],"english")
        with self.assertRaises(ValueError):
            trial.parse_srt(first+"\n"+first)

    def test_json_request_localhost_bound(self):
        # No public network. The default body must not use chat completions:
        # PFN's direct PFML3 API is distinct from the older Ollama prompt.
        self.assertIn("plamo-3-translate-2b-Q4_K_M.gguf",trial.MODEL_FILES["2b"])
        self.assertIn("plamo-3-translate-0.8b-Q4_K_M.gguf",trial.MODEL_FILES["0.8b"])

    def test_self_test(self):
        trial.self_test()


if __name__=="__main__":
    unittest.main()
