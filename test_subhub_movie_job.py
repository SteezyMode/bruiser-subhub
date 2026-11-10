"""Regression: a Japanese source miss is not English-transcript failure or a translation launch."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools import subhub_movie_job as movie


class MovieSourceMissTests(unittest.TestCase):
    def test_source_miss_does_not_claim_immediate_translation(self):
        video = Path("/mnt/2TB/Plex Expansion/Movies/Example.mkv")

        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(
                args, 0, stdout=b"SOURCE_MISS: no approved candidate\n", stderr=b""
            )

        # The fixture is a readable local file and is used only as worker stdin.
        with patch.object(movie, "RESCUE", Path(__file__)), \
             patch.object(movie.publisher, "video_safety", return_value=video), \
             patch.object(movie.publisher, "existing_ja", return_value=False), \
             patch.object(movie.publisher, "container_path", return_value="/media/Example.mkv"):
            result = movie.run_one(video, "Example", 2020, apply=True, runner=fake_run)
        self.assertEqual(result["state"], "missing_ja")
        self.assertIn("Review saved candidates", result["message"])
        self.assertIn("English is not required", result["message"])
        self.assertNotIn("translation is next", result["message"])


if __name__ == "__main__":
    unittest.main()
