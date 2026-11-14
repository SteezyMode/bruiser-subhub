#!/usr/bin/env python3
"""Offline regression tests for library-wide Japanese sourcing.

No provider calls, no media writes, no Jellyfin/Sublarr connection and no
AI invocation. Exercise the actual publisher CLI with a simulated prior
deterministic failure, and verify anime is excluded from ordinary scopes.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ja_first_movie_scope as scope


class ScopeTests(unittest.TestCase):
    ROOT = "/mnt/2TB/Plex Expansion/Movies"

    def movie(self, **overrides):
        row = {
            "kind": "Movie",
            "title": "Placeholder",
            "host_path": self.ROOT + "/Animation/film.mkv",
            "genres": ["Animation"],
            "original_title": "",
            "production_locations": [],
            "studios": [],
        }
        row.update(overrides)
        return row

    def test_japanese_animation_excluded_english_dub(self):
        film = self.movie(title="Japanese animated film",
                          original_title="もののけ姫")
        self.assertTrue(scope.is_anime_movie(film))
        self.assertFalse(scope.matches(film, "all"))
        self.assertFalse(scope.matches(film, "movies-no-anime"))
        self.assertTrue(scope.matches(film, "movies-all"))

    def test_studio_and_country_metadata(self):
        self.assertFalse(scope.matches(
            self.movie(studios=["Studio Ghibli"]), "all"))
        self.assertFalse(scope.matches(
            self.movie(production_locations=["Japan"]), "all"))

    def test_western_animation_and_episode_remain_eligible(self):
        self.assertTrue(scope.matches(self.movie(), "all"))
        self.assertTrue(scope.matches(self.movie(), "movies-no-anime"))
        self.assertTrue(scope.matches({"kind": "Episode",
                                      "genres": ["Animation"]}, "all"))

    def test_anime_folder_not_confused_with_animated(self):
        self.assertFalse(scope.matches(self.movie(
            host_path=self.ROOT + "/Anime/film.mkv",
            genres=["Fantasy"]), "all"))
        self.assertTrue(scope.matches(self.movie(
            host_path=self.ROOT + "/Animated/film.mkv",
            genres=["Animation"]), "all"))


class PublisherReceiptTests(unittest.TestCase):
    def test_prior_failed_movie_emits_exact_machine_receipt(self):
        import benchmark_subtitle_search_paths as manifest
        import ja_first_publish_queue as publisher

        jid = "a" * 32
        row = {
            "jellyfin_id": jid,
            "kind": "Movie",
            "title": "Test live action",
            "host_path": "/mnt/2TB/Plex Expansion/Movies/Drama/film.mkv",
            "genres": ["Drama"],
            "original_title": "Test live action",
        }
        stdout = StringIO()
        with mock.patch.object(publisher, "stages",
                               return_value=[(jid, "12345", "b" * 64)]), \
             mock.patch.object(manifest, "load_latest_manifest",
                               return_value=[row]), \
             mock.patch.object(publisher, "choose",
                               return_value=("held_unchanged", row, None)), \
             mock.patch.object(publisher, "report_next_action",
                               return_value="stage_alternate_saved_japanese"), \
             mock.patch.object(publisher, "retain_movie_outcome"), \
             mock.patch.object(sys, "argv", ["publisher", "--apply"]), \
             redirect_stdout(stdout):
            publisher.main()

        receipts = [json.loads(line.partition(":")[2])
                    for line in stdout.getvalue().splitlines()
                    if line.startswith("BRUISER_PUBLISH_ITEM:")]
        self.assertEqual(receipts, [
            {"jellyfin_id": jid, "result": "held",
             "reason": "unchanged_deterministic_hold"}
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
