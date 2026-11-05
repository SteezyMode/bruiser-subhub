"""Offline checks for PFN-native real-film PLaMo evaluation; no host or GPU."""
import unittest
import tempfile
from pathlib import Path
from unittest import mock
import json
import hashlib
from tools import plamo3_real_film_ab as real

class RealFilmPFNTests(unittest.TestCase):
    def test_exact_pfn_input_output_history_order(self):
        prompt = real.native_prompt("That's not what I meant.", [
            ("Don't touch it.", "触るな。"),
            ("I'm serious.", "本気だ。"),
        ])
        self.assertTrue(prompt.startswith(
            "<|plamo:tag|>dataset<|plamo:msg|>translation"))
        self.assertEqual(prompt.count("<|plamo:tag|>input"), 3)
        self.assertEqual(prompt.count("<|plamo:tag|>output"), 3)
        self.assertLess(prompt.index("Don't touch it."), prompt.index("触るな。"))
        self.assertLess(prompt.index("触るな。"), prompt.index("I'm serious."))
        self.assertLess(prompt.index("本気だ。"), prompt.index("That's not what I meant."))
        self.assertTrue(prompt.endswith(
            "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja<|plamo:msg|>"))
        self.assertNotIn("<|plamo:bos|>", prompt)

    def test_no_history_and_invalid_input(self):
        prompt = real.native_prompt("We're leaving.", [])
        self.assertEqual(prompt.count("<|plamo:tag|>input"), 1)
        self.assertEqual(prompt.count("<|plamo:tag|>output"), 1)
        with self.assertRaises(ValueError):
            real.native_prompt("", [])
        with self.assertRaises(ValueError):
            real.native_prompt("Hello", [("hi", "")])
        with self.assertRaises(ValueError):
            real.native_prompt("Hi <|plamo:tag|>", [])

    def test_contract(self):
        self.assertEqual(real.LIMIT, 100)
        self.assertEqual(real.HISTORY, 2)
        self.assertEqual(real.STOP, ["<|plamo:tag|>", "<|plamo:bos|>"])
        self.assertIn("pfnet", real.PFN_URL)

    def test_non_dialogue_caption_not_mistranslated(self):
        self.assertTrue(real.is_non_dialogue_caption(
            '<font size="36">[SIGHS]</font>'))
        self.assertTrue(real.is_non_dialogue_caption(
            '<i>[MUSIC PLAYING]</i>'))
        self.assertTrue(real.is_non_dialogue_caption('[SCREAMS]'))
        self.assertFalse(real.is_non_dialogue_caption(
            '<font size="36">You should have treated her right.</font>'))
        self.assertFalse(real.is_non_dialogue_caption(
            '[SIGHS] You should have treated her right.'))
        self.assertFalse(real.is_non_dialogue_caption(
            'Run!'))

    def test_dialogue_without_japanese_is_recorded_as_held(self):
        with mock.patch.object(real.small, "json_request", return_value={
            "choices": [{"text": "Jason!", "finish_reason": "stop"}],
            "usage": {"completion_tokens": 3},
        }) as call:
            output, usage, status = real.request(18879, "Jason!", [])
        self.assertEqual(output, "Jason!")
        self.assertEqual(status, "held_non_japanese")
        self.assertEqual(usage["completion_tokens"], 3)
        args = call.call_args.args
        self.assertEqual(args[1], "/v1/completions")
        self.assertEqual(args[2]["temperature"], 0)
        self.assertEqual(args[2]["max_tokens"], 512)
        self.assertEqual(args[2]["stop"], real.STOP)

    def test_frozen_source_preserves_exact_100_cues(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / "real-results"
            source_dir.mkdir(mode=0o700)
            frozen = source_dir / "film-100-original"
            frozen.mkdir(mode=0o700)
            video = root / "movie.mkv"
            video.write_bytes(b"sample original media identifier")
            st = video.stat()
            rows = [
                {"number": 153 + i, "start": real.small.timestamp(i * 5),
                 "end": real.small.timestamp(i * 5 + 4), "english": "Hello."}
                for i in range(real.LIMIT)
            ]
            data = real.small.format_srt(rows, "english").encode("utf-8")
            en = frozen / "source.en.srt"
            en.write_bytes(data)
            en.chmod(0o600)
            details = {
                "source_sha256": hashlib.sha256(data).hexdigest(),
                "selected_cues": 100, "first_cue": 153, "last_cue": 252,
                "all_source_cues": 764, "title": "Test Film",
                "video_path": str(video), "video_bytes": st.st_size,
                "media_mtime_ns": st.st_mtime_ns,
                "jellyfin_id": "test", "manifest": "intake.json",
            }
            manifest = frozen / "manifest.json"
            manifest.write_text(json.dumps(details))
            manifest.chmod(0o600)
            with mock.patch.object(real, "ROOT", root):
                got = real.load_frozen_run(frozen)
                self.assertEqual(len(got[2]), 100)
                self.assertEqual(got[2][0]["number"], 153)
                self.assertEqual(got[2][-1]["number"], 252)
                self.assertEqual(got[-1], details["source_sha256"])
                en.write_bytes(data + b"tampered")
                with self.assertRaisesRegex(RuntimeError, "sha_mismatch"):
                    real.load_frozen_run(frozen)

    def test_completed_0_8b_reference_must_match_all_100_english_cues(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            rows = [
                {"number": 153 + i, "start": real.small.timestamp(i*5),
                 "end": real.small.timestamp(i*5+4), "english": "Hello."}
                for i in range(100)]
            reference = {
                "status": "complete",
                "entries": [dict(row, status="translated", japanese="こんにちは")
                            for row in rows],
            }
            ref = path / "0.8b.json"
            ref.write_text(json.dumps(reference), encoding="utf-8")
            ref.chmod(0o600)
            got = real.verify_completed_reference(path, rows)
            self.assertEqual(got, hashlib.sha256(ref.read_bytes()).hexdigest())
            reference["entries"][19]["english"] = "changed"
            ref.write_text(json.dumps(reference), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"reference_0_8b_source_mismatch"):
                real.verify_completed_reference(path, rows)
            reference["entries"][19]["english"] = "Hello."
            reference["status"] = "started"
            ref.write_text(json.dumps(reference), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"reference_0_8b_not_complete"):
                real.verify_completed_reference(path, rows)

    def test_self_test(self):
        real.tests()

if __name__ == "__main__":
    unittest.main()
