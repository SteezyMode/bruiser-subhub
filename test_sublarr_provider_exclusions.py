"""Read-only non-core provider rejection census, without weakening staging."""
import io
import json
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch

from tools import ja_first_stage_sublarr as generic


def movie(jid,title,year,*,genres=None):
    return {"jellyfin_id":jid,"kind":"Movie","status":"ready_ja_search",
            "title":title,"year":year,"genres":genres or ["Drama"],
            "host_path":"/mnt/2TB/Plex Expansion/Movies/Drama/file.mkv"}


def candidate(provider="subf2m",filename="Real.Film.2017.Japanese.srt",
              **overrides):
    base={"provider":provider,"subtitle_id":"provider-id-1234","language":"ja",
          "format":"srt","filename":filename,
          "release_info":"Real.Film.2017.WEB-DL","grade":"review"}
    base.update(overrides)
    return base


class ProviderExclusionTests(unittest.TestCase):
    def test_exclusions_are_specific_and_no_staging_rules_changed(self):
        row=movie("a"*32,"Real Film",2017)
        self.assertEqual(generic.exclusion_reason(row,candidate()),"eligible")
        self.assertEqual(generic.exclusion_reason(
            row,candidate(language="en")),"language_not_japanese")
        self.assertEqual(generic.exclusion_reason(
            row,candidate(format="ass")),"unsupported_format")
        self.assertEqual(generic.exclusion_reason(
            row,candidate(forced=True)),"forced_or_signs_only")
        self.assertEqual(generic.exclusion_reason(
            row,candidate(filename="Other.Film.2003.Japanese.srt",
                          release_info="Other.Film.2003.WEB-DL")),
            "unverified_movie_title_or_year")
        self.assertEqual(generic.exclusion_reason(
            row,candidate(provider="subdl")),"not_generic_or_invalid_provider_id")

    def test_census_counts_rejected_separately_and_favors_non_animation(self):
        live=movie("a"*32,"Real Film",2017)
        animated=movie("b"*32,"Animated Story",2017,genres=["Animation"])
        docs=[
            (live["jellyfin_id"],json.dumps({
                "candidates":[candidate(),candidate(format="ass"),
                              candidate(provider="animetosho",language="en")],
                "rejected_candidates":[candidate(subtitle_id="reject-1")]})),
            (animated["jellyfin_id"],json.dumps({
                "candidates":[candidate(provider="kitsunekko",
                    filename="Animated.Story.2017.Japanese.srt",
                    release_info="Animated.Story.2017.WEB-DL")]}))]
        output=io.StringIO()
        with patch.object(generic.stage,"read_inventory",return_value={
                live["jellyfin_id"]:live,animated["jellyfin_id"]:animated}), \
             patch.object(generic.stage,"read_saved_searches",return_value=docs), \
             patch.object(generic,"provider_bytes") as download, \
             patch.object(generic,"preserve") as stage, redirect_stdout(output):
            generic.exclusion_audit()
            download.assert_not_called()
            stage.assert_not_called()
        rendered=output.getvalue()
        self.assertIn("discovery_rejected_eligible",rendered)
        self.assertIn("unsupported_format",rendered)
        self.assertIn("language_not_japanese",rendered)
        self.assertIn("Real Film",rendered)
        self.assertNotIn("PILOT: "+animated["jellyfin_id"],rendered)
        self.assertIn("ZERO searches, downloads, stages",rendered)

    def test_option_rejects_any_apply_combination(self):
        with self.assertRaises(SystemExit):
            generic.main(["--audit-exclusions","--apply"])


if __name__=="__main__":
    unittest.main()
