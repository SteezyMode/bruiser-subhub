#!/usr/bin/env python3
"""Offline safety tests for the one-title SubHub v2 handoff (no Docker/Ollama)."""
import importlib.util
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("v2", HERE / "subhub_v2_one_title.py")
v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)


class V2SafetyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "A Movie (2009).mp4"
        self.video.write_bytes(b"not-a-real-video")
        self.en = self.root / "source.en.srt"
        self.ja = self.root / "translated.ja.srt"
        self.en.write_text(
            "1\n00:00:01,000 --> 00:00:02,500\nCut it!\n\n"
            "2\n00:00:04,000 --> 00:00:05,500\nKeep quiet.\n",
            encoding="utf-8",
        )
        self.ja.write_text(
            "1\n00:00:01,000 --> 00:00:02,500\n切れ！\n\n"
            "2\n00:00:04,000 --> 00:00:05,500\n静かにして。\n",
            encoding="utf-8",
        )

    def test_uncaptured_commands_really_execute(self):
        # Regression: a conditional return once skipped subprocess.run
        # for ALL normal Docker operations and reported a false success.
        with patch.object(v2.subprocess, "run", return_value=SimpleNamespace(stdout=None)) as runner:
            self.assertIsNone(v2.cmd("docker", "exec", "sublarr-pilot", "true"))
            runner.assert_called_once_with(
                ["docker", "exec", "sublarr-pilot", "true"],
                check=True, text=True, stdout=None,
            )

    def test_captured_commands_return_output(self):
        with patch.object(v2.subprocess, "run", return_value=SimpleNamespace(stdout='{"ok":true}')) as runner:
            self.assertEqual(v2.cmd("docker", "inspect", "sublarr-pilot", capture=True), '{"ok":true}')
            runner.assert_called_once_with(
                ["docker", "inspect", "sublarr-pilot"],
                check=True, text=True, stdout=v2.subprocess.PIPE,
            )

    def test_correct_alignment(self):
        self.assertEqual(v2.validate(self.en, self.ja), 2)

    def test_reject_missing_cues(self):
        self.ja.write_text(
            "1\n00:00:01,000 --> 00:00:02,500\n切れ！\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            v2.validate(self.en, self.ja)

    def test_reject_timestamp_changes(self):
        self.ja.write_text(
            self.ja.read_text().replace("00:00:04,000", "00:00:04,500"),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            v2.validate(self.en, self.ja)

    def test_create_only_preserves_existing(self):
        dest = self.root / "new.ja.srt"
        v2.create_only_copy(self.ja, dest)
        self.assertEqual(dest.read_bytes(), self.ja.read_bytes())
        self.ja.write_text("bad text", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            v2.create_only_copy(self.ja, dest)
        self.assertNotEqual(dest.read_bytes(), self.ja.read_bytes())

    def test_japanese_sidecar_detection(self):
        self.assertEqual(v2.japanese_sidecars(self.video), [])
        ja = self.root / "A Movie (2009).ja.srt"
        ja.write_text("never overwrite", encoding="utf-8")
        self.assertEqual(v2.japanese_sidecars(self.video), [ja])


if __name__ == "__main__":
    unittest.main()
