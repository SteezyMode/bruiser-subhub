"""Native Jellyfin series identity fallback for JA sourcing (offline).

No network, provider calls, subtitle writes, or actual video parsing.
"""
from pathlib import Path
import tempfile
import subprocess
import unittest
import re

from tools import ja_first_catalog_manifest as catalog
from tools import ja_first_search_pilot as search
from tools import ja_first_stage_saved_batch as stage


class NativeSeriesIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "Its.Always.Sunny.in.Philadelphia.S12E02.mkv"
        self.video.write_bytes(b"fixture")
        self.series_id = "a" * 32
        self.mounts = [(self.root, Path("/media/bigdisk-video"))]
        self.item = {
            "Id": "b" * 32, "Type": "Episode",
            "Name": "The Gang Goes to a Water Park",
            "Path": str(self.video), "SeriesId": self.series_id,
            "SeriesName": "It's Always Sunny in Philadelphia",
            "ParentIndexNumber": 12, "IndexNumber": 2,
            "MediaStreams": [{"Type": "Audio", "Language": "eng",
                              "IsDefault": True}],
        }
        self.series = {self.series_id: {
            "Id": self.series_id,
            "Name": "It's Always Sunny in Philadelphia",
            "ProviderIds": {},
        }}
        self.candidate = {
            "provider": "opensubtitles", "subtitle_id": "123456",
            "language": "ja", "forced": False, "kind": "subtitle",
            "filename": "Its.Always.Sunny.in.Philadelphia.S12E02.720p.WEB.ja.srt",
            "release_info": "",
            "matches": ["series", "season", "episode"],
        }

    def inspect(self):
        return catalog.classify(self.item, self.series, self.mounts, {})

    def test_no_external_series_ids_can_be_search_ready(self):
        row = self.inspect()
        self.assertEqual(row["status"], "ready_ja_search")
        self.assertEqual(row["series_identity_source"], "jellyfin")
        self.assertEqual(row["series_jellyfin_id"], self.series_id)
        self.assertEqual(row["audio_language"], "eng")
        self.assertTrue(stage.identity_ok(row, self.candidate))
        q = search.query_for(row)
        self.assertEqual((q["series_title"], q["season"], q["episode"]),
                         ("It's Always Sunny in Philadelphia", 12, 2))
        self.assertEqual(q["language"], "ja")
        self.assertNotIn("imdb_id", q)

    def test_episode_series_id_and_name_works_without_parent_listing(self):
        self.series = {}
        row = self.inspect()
        self.assertEqual(row["status"], "ready_ja_search")
        self.assertEqual(row["series_identity_source"], "jellyfin")

    def test_provider_ids_still_take_precedence(self):
        self.series[self.series_id]["ProviderIds"] = {"Imdb": "tt0472954"}
        row = self.inspect()
        self.assertEqual(row["series_identity_source"], "provider")
        self.assertEqual(row["series_imdb_id"], "tt0472954")

    def test_bad_or_missing_native_identity_blocks(self):
        self.item["SeriesId"] = ""
        self.assertEqual(self.inspect()["status"], "review_missing_series_identity")
        self.item["SeriesId"] = self.series_id
        self.series[self.series_id]["Id"] = "c" * 32
        self.assertEqual(self.inspect()["status"], "review_missing_series_identity")
        self.series[self.series_id]["Id"] = self.series_id
        self.series[self.series_id]["Name"] = "Unrelated Series"
        self.assertEqual(self.inspect()["status"], "review_missing_series_identity")

    def test_no_audio_language_does_not_use_native_identity_to_bypass_review(self):
        self.item["MediaStreams"] = [{"Type": "Audio", "Language": "und"}]
        self.assertEqual(self.inspect()["status"], "review_audio_language_unverified")

    def test_safe_installer_has_valid_shell_syntax(self):
        installer = (Path(__file__).parent / "tools" /
                     "install_native_series_identity_fix.sh")
        result = subprocess.run(["bash", "-n", str(installer)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_installer_embedded_python_and_audio_override(self):
        """The known local drift is reconstructed exactly, not ignored."""
        installer = (Path(__file__).parent / "tools" /
                     "install_native_series_identity_fix.sh")
        content = installer.read_text(encoding="utf-8")
        scripts = re.findall(r"<<'PY'\n(.*?)\nPY", content, re.S)
        self.assertGreaterEqual(len(scripts), 2)
        for script in scripts:
            compile(script, "<installer-embedded-python>", "exec")
        section = scripts[0]
        start = section.index("def omit_unknown_audio_gate(content):")
        end = section.index("\nold = old_manifest")
        namespace = {}
        exec(section[start:end], namespace)
        original = (
            'UNKNOWN_AUDIO = {"", "und", "unknown", "mul", "zxx", "none"}\n'
            'COUNTS = ("existing_japanese_subtitle",\n'
            '          "review_audio_language_unverified", "review_no_movie_imdb", "review_missing_series_identity",\n'
            '    elif audio_lang in UNKNOWN_AUDIO:\n'
            '        # A present audio stream with no language tag is NOT evidence of EN\n'
            '        # audio. Never spend JA search quota on a potentially Japanese show.\n'
            '        data["status"] = "review_audio_language_unverified"\n'
            '    assert lang("und") in UNKNOWN_AUDIO and lang("jpn") not in UNKNOWN_AUDIO\n'
            'OTHER_CODE_UNCHANGED = True\n'
        )
        adapted = namespace["omit_unknown_audio_gate"](original)
        self.assertNotIn("UNKNOWN_AUDIO", adapted)
        self.assertNotIn("review_audio_language_unverified", adapted)
        self.assertIn("OTHER_CODE_UNCHANGED = True", adapted)

    def test_external_matching_remains_strict(self):
        row = self.inspect()
        self.assertFalse(stage.identity_ok(row, {
            **self.candidate, "filename": "Its.Always.Sunny.in.Philadelphia.S12E03.ja.srt"
        }))
        self.assertFalse(stage.identity_ok(row, {
            **self.candidate, "filename": "Different.Show.S12E02.ja.srt"
        }))
        self.assertFalse(stage.identity_ok(row, {
            **self.candidate, "matches": ["season", "episode"]
        }))
        self.assertFalse(stage.identity_ok({
            **row, "series_identity_source": "",
            "series_jellyfin_id": ""
        }, self.candidate))


if __name__=="__main__":
    unittest.main()
