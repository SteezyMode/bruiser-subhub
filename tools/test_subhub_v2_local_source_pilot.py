#!/usr/bin/env python3
"""Offline regression tests for v2 local subtitle source selection."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "source_selector", HERE / "subhub_v2_local_source_pilot.py"
)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def subtitles(count=410):
    return "\n\n".join(
        f"{n}\n00:00:01,000 --> 00:00:02,000\nWe need to get out of here."
        for n in range(1, count + 1)
    ) + "\n"


class Bridge:
    @staticmethod
    def japanese_sidecars(video):
        return list(video.parent.glob(video.stem + ".ja.srt"))

    @staticmethod
    def read_srt(path):
        import re
        blocks = re.split(r"\n\n+", path.read_text(encoding="utf-8").strip())
        return [(int(b.splitlines()[0]), b.splitlines()[1], "\n".join(b.splitlines()[2:])) for b in blocks]


class TestV2LocalSource(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.state = self.root / "private-state"
        self.movie = self.root / "Another Horror Film (2024).mkv"
        self.movie.write_bytes(b"fixture")
        self.probe_result = {"streams": [
            {"index": 0, "codec_type": "audio", "tags": {"language": "eng"}}
        ]}

    def test_plain_release_matched_srt(self):
        sidecar = self.movie.with_suffix(".srt")
        sidecar.write_text(subtitles(), encoding="utf-8")
        with patch.object(selector, "probe", return_value=self.probe_result):
            found = selector.select(Bridge, [self.root], self.state, scan_limit=10)
        self.assertEqual(found, (self.movie, sidecar))

    def test_existing_japanese_protected(self):
        self.movie.with_suffix(".srt").write_text(subtitles(), encoding="utf-8")
        self.movie.with_suffix(".ja.srt").write_text("original", encoding="utf-8")
        with patch.object(selector, "probe", return_value=self.probe_result):
            found = selector.select(Bridge, [self.root], self.state, scan_limit=10)
        self.assertIsNone(found)

    def test_embedded_english_extraction(self):
        self.probe_result["streams"].append({
            "index": 2, "codec_type": "subtitle", "codec_name": "subrip",
            "tags": {"language": "eng"},
        })

        def fake_extract(video, index, output):
            self.assertEqual(video, self.movie)
            self.assertEqual(index, 2)
            output.parent.mkdir(parents=True, exist_ok=True)
            raw = output.parent / "fresh-extraction.srt"
            raw.write_text(subtitles(), encoding="utf-8")
            return raw

        with patch.object(selector, "probe", return_value=self.probe_result), \
             patch.object(selector, "extract_embedded", side_effect=fake_extract):
            found = selector.select(Bridge, [self.root], self.state, scan_limit=10)
        self.assertEqual(found[0], self.movie)
        self.assertTrue(found[1].is_file())
        self.assertTrue(found[1].name.endswith(".en.srt"))

    def test_japanese_text_not_misidentified_as_english(self):
        source = self.movie.with_suffix(".srt")
        source.write_text(subtitles().replace("We need to get out of here.", "ここから逃げよう"), encoding="utf-8")
        with patch.object(selector, "probe", return_value=self.probe_result):
            self.assertIsNone(selector.select(Bridge, [self.root], self.state, scan_limit=10))


if __name__ == "__main__":
    unittest.main()
