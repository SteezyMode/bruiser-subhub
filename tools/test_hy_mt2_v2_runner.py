#!/usr/bin/env python3
"""Offline tests for v2 singleton format rescue; Tencent settings unchanged."""
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v2 = load("hy_mt2_v2", "hy_mt2_v2_runner.py")
baseline = load("hy_mt2_baseline", "hy_mt2_full_srt_test.py")
CUE = [("120", "00:11:35,100 --> 00:11:36,600", "From the tour requests.")]


class TestSingletonFormatRecovery(unittest.TestCase):
    def test_model_prompt_and_sampling_unchanged(self):
        self.assertEqual(v2.MODEL, baseline.MODEL)
        self.assertEqual(v2.OPTIONS, baseline.OPTIONS)
        for example in ("", "120\n00:11:35,100 --> 00:11:36,600\nFrom the tour requests.\n"):
            self.assertEqual(v2.official_prompt(example), baseline.official_prompt(example))

    def test_plain_japanese_wraps_exact_source_header(self):
        got = v2.wrap_plain_japanese_singleton(CUE, "ツアーの要求から。")
        self.assertEqual(got, [("120", "00:11:35,100 --> 00:11:36,600", "ツアーの要求から。")])
        self.assertEqual(v2.compare_structure(CUE, v2.as_srt(got)), got)

    def test_no_recovery_for_multicue_or_explanations(self):
        cases = [
            "Here is the translation: ツアーの要求から。",
            "120\n00:11:35,100 --> 00:11:36,600",
            chr(96) * 3 + "\nツアーの要求から。\n" + chr(96) * 3,
            "One hundred twenty",
            "",
            "ツアーの要求から。\n\n余計な段落",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertIsNone(v2.wrap_plain_japanese_singleton(CUE, raw))
        self.assertIsNone(v2.wrap_plain_japanese_singleton(CUE + CUE, "ツアーの要求から。"))


if __name__ == "__main__":
    unittest.main()
