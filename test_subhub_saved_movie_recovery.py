"""Offline regression: saved candidate recovery never searches providers or runs AI."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import subhub_saved_movie_recovery as saved


def film(jid="a"*32,title="Recovered Film"):
    return {
        "jellyfin_id":jid, "kind":"Movie","title":title,"year":2020,
        "status":"ready_ja_search", "genres":["Horror"],
        "host_path":"/mnt/2TB/Plex Expansion/Movies/Horror/Recovered Film.mkv",
    }


def search_record(jid):
    return {"_outcome":"review","candidates":[{"provider":"opensubtitles",
        "language":"ja","subtitle_id":"123456","filename":"Recovered.Film.2020.ja.srt",
        "matches":["title"]}]}


class SavedMovieRecoveryTests(unittest.TestCase):
    def test_deduplicate_saved_staged_and_invalid_downloads(self):
        row=film()
        good={"provider":"opensubtitles","subtitle_id":"123456"}
        bad={"provider":"opensubtitles","subtitle_id":"234567"}
        sub={"provider":"subdl","subtitle_id":"some-subdl-remote-id"}
        with patch.object(saved.deep,"candidates_for",
                          return_value=[good,bad,sub]), \
             patch.object(saved.subdl,"numeric_id",
                          return_value=("10123456","digest")):
            result,skipped=saved.fresh_candidates(
                row,{}, {(row["jellyfin_id"],"123456")},
                set(),rejected_check=lambda r,c:c is bad)
        self.assertEqual(result,[sub])
        self.assertEqual(skipped["already_staged"],1)
        self.assertEqual(skipped["known_invalid_download"],1)

    def test_review_and_plausible_only_in_horror_drama_scope(self):
        row=film()
        movie_outside=dict(film("b"*32,"Action Film"),
            genres=["Action"],
            host_path="/mnt/2TB/Plex Expansion/Movies/Action/Action Film.mkv")
        covered=dict(film("c"*32,"Already Covered"),
            status="existing_japanese_subtitle")
        docs={row["jellyfin_id"]:search_record(row["jellyfin_id"])}
        with patch.object(saved.deep,"candidates_for",return_value=[
            {"provider":"opensubtitles","subtitle_id":"123456"}]):
            jobs,counts,_=saved.saved_work(
                [row,movie_outside,covered],staged=set(),rejected=set(),
                search_reader=lambda jid:docs.get(jid),
                rejected_check=lambda *_:False)
        self.assertEqual([r["jellyfin_id"] for r,_ in jobs],[row["jellyfin_id"]])
        self.assertEqual(counts["saved_review_or_plausible"],1)
        self.assertEqual(counts["titles_with_new_verified_candidates"],1)

    def test_owner_skips_the_master_without_touching_it(self):
        row=film(title="The Master")
        jobs,counts,_=saved.saved_work(
            [row],skip_titles={"the master"},staged=set(),rejected=set(),
            search_reader=lambda _:search_record("a"*32))
        self.assertEqual(jobs,[])
        self.assertEqual(counts["owner_skipped"],1)

    def test_readonly_mode_never_stages_or_publishes_or_searches(self):
        rows=[film()]
        with tempfile.TemporaryDirectory() as tmp:
            fd=os.open(str(Path(tmp)/"lock"),os.O_CREAT|os.O_RDWR,0o600)
            with patch.object(saved,"check_idle"), \
                 patch.object(saved.autofill,"lock",return_value=fd), \
                 patch.object(saved.stage,"private_root"), \
                 patch.object(saved.stage,"read_inventory",
                              return_value={row["jellyfin_id"]:row for row in rows}), \
                 patch.object(saved,"saved_work",return_value=(
                     [(rows[0],[{"provider":"opensubtitles","subtitle_id":"123456"}])],
                     {"saved_review_or_plausible":1},[])), \
                 patch.object(saved,"stage_candidate") as candidate, \
                 patch.object(saved.deep,"repair_staged") as publish:
                self.assertEqual(saved.run(SimpleNamespace(
                    skip_title=[],apply=False,max_attempts=5,max_per_title=2)),0)
                candidate.assert_not_called()
                publish.assert_not_called()

    def test_quotas_and_stage_receipts_are_classified(self):
        with patch.object(saved.subprocess,"run") as run:
            run.return_value=SimpleNamespace(
                returncode=0,stdout="PROVIDER_LIMIT_REACHED: OpenSubtitles",
                stderr="")
            self.assertEqual(saved.stage_candidate(
                "a"*32,{"provider":"opensubtitles","subtitle_id":"123456"})[0],
                "quota")
            self.assertTrue(any("ja_first_stage_saved_batch.py" in p
                 for p in run.call_args.args[0]))
            self.assertNotIn("ja_first_search_pilot.py",
                             " ".join(map(str,run.call_args.args[0])))
            run.return_value=SimpleNamespace(
                returncode=0,stdout="STAGED: saved/private/track.ja.srt",
                stderr="")
            self.assertEqual(saved.stage_candidate(
                "a"*32,{"provider":"opensubtitles","subtitle_id":"123456"})[0],
                "staged")


if __name__=="__main__":
    unittest.main()
