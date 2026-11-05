"""Offline regression: reproduce a failed PLaMo cue without losing raw evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from tools import plamo3_reproduce_held_cue as diag
from tools import plamo3_small_ab as small


class ReproHeldCueTests(unittest.TestCase):
    def test_raw_response_not_confused_with_validation(self):
        r = diag.summarize_result({"choices":[{"text":"Jason", "finish_reason":"stop"}]})
        self.assertEqual(r["raw_translation"], "Jason")
        self.assertFalse(r["japanese_script"])
        self.assertFalse(r["blank"])
        self.assertEqual(r["finish_reason"], "stop")
        r = diag.summarize_result({"choices":[{"text":"女の子", "finish_reason":"stop"}]})
        self.assertTrue(r["japanese_script"])

    def test_model_parameters_unchanged_and_native_history(self):
        with mock.patch.object(diag.small, "json_request", return_value={"choices":[]}) as call:
            diag.raw_completion(18881, "Go!", [("Come back.", "戻れ。")])
        args, kw = call.call_args
        self.assertEqual(args[:2], (18881, "/v1/completions"))
        payload = args[2]
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["stop"], diag.real.STOP)
        self.assertTrue(payload["prompt"].endswith(
            "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja<|plamo:msg|>"))
        self.assertIn("戻れ。", payload["prompt"])
        self.assertEqual(kw["timeout"], 180)

    def test_frozen_run_integrity_and_next_cue(self):
        cues = small.samples()[:4]
        data = small.format_srt(cues, "english").encode()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/"source.en.srt").write_bytes(data)
            (folder/"manifest.json").write_text(json.dumps({
                "source_sha256":hashlib.sha256(data).hexdigest(), "title":"Test"}))
            (folder/"0.8b.json").write_text(json.dumps({"entries":[{
                **cues[0], "japanese":"日本語"}]}))
            # TempDirectory permissions and umask are environment-specific.
            with mock.patch.object(diag.real, "_private_path", side_effect=lambda x:x):
                found, rows, entries, history, _ = diag.find_cue(folder, "0.8b")
                self.assertEqual(len(entries), 1)
                self.assertEqual(rows[1]["number"], 2)
                self.assertEqual(history, [(cues[0]["english"], "日本語")])
                (folder/"manifest.json").write_text(json.dumps({"source_sha256":"0"*64}))
                with self.assertRaisesRegex(RuntimeError,"sha256"):
                    diag.find_cue(folder,"0.8b")

    def test_self_test(self):
        diag.tests()


if __name__ == "__main__":
    unittest.main()
