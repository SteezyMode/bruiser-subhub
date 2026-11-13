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

    def test_saved_candidates_are_scoped_to_each_movie_library_genre(self):
        horror=film("a"*32,"Horror Film")
        drama=dict(film("b"*32,"Drama Film"),genres=["Drama"],
                   host_path="/mnt/BigDisk/Video/Movies/Drama, Suspense/Drama.mkv")
        action=dict(film("c"*32,"Action Film"),genres=["Action"],
                    host_path="/mnt/2TB/Plex Expansion/Movies/Action/Action.mkv")
        covered=dict(film("d"*32,"Covered Drama"),genres=["Drama"],
                     host_path="/mnt/BigDisk/Video/Movies/Drama/Covered.mkv",
                     status="existing_japanese_subtitle")
        tv=dict(film("e"*32,"Drama Series"),kind="Episode",genres=["Drama"],
                host_path="/mnt/2TB/Plex Expansion/Television/Drama/Show.mkv")
        items=[horror,drama,action,covered,tv]
        docs={r["jellyfin_id"]:search_record(r["jellyfin_id"]) for r in items}
        with patch.object(saved.deep,"candidates_for",return_value=[
             {"provider":"opensubtitles","subtitle_id":"123456"}]):
            for scope,expected in (("movies-drama",drama),("movies-horror",horror),
                                   ("movies-action",action)):
                with self.subTest(scope=scope):
                    jobs,counts,_=saved.saved_work(
                        items,scope=scope,staged=set(),rejected=set(),
                        search_reader=lambda jid:docs.get(jid),
                        rejected_check=lambda *_:False)
                    self.assertEqual([r["jellyfin_id"] for r,_ in jobs],
                                     [expected["jellyfin_id"]])
                    self.assertEqual(counts["titles_with_new_verified_candidates"],1)
        with self.assertRaisesRegex(ValueError,"requires_movie_scope"):
            saved.saved_work(items,scope="all")

    def test_review_only_recovers_verified_review_grade_not_existing_plausible(self):
        row=film()
        documents={row["jellyfin_id"]:{"_outcome":"plausible","candidates":[
            {"provider":"subdl","grade":"plausible","subtitle_id":"other"},
            {"provider":"opensubtitles","grade":"review","subtitle_id":"123456"},
            {"provider":"opensubtitles","grade":"review","subtitle_id":"234567"},
        ]}}
        with patch.object(saved.deep,"candidates_for",
                          return_value=documents[row["jellyfin_id"]]["candidates"]):
            jobs,counts,_=saved.saved_work(
                [row],scope="movies-horror",staged={(row["jellyfin_id"],"234567")},
                rejected=set(),search_reader=lambda _:documents[row["jellyfin_id"]],
                rejected_check=lambda *_:False,review_only=True)
        self.assertEqual(len(jobs),1)
        self.assertEqual([x["subtitle_id"] for x in jobs[0][1]],["123456"])
        self.assertEqual(counts["skipped_not_review_candidate"],1)
        self.assertEqual(counts["skipped_already_staged"],1)
        bad=dict(film("b"*32,"Covered"),status="existing_japanese_subtitle")
        jobs,counts,_=saved.saved_work(
            [bad],scope="movies-horror",staged=set(),rejected=set(),
            search_reader=lambda _:{"_outcome":"review","candidates":[
                {"grade":"review"}]},review_only=True)
        self.assertEqual(jobs,[])

    def test_readonly_audit_explains_unverified_review_releases_without_download(self):
        row=film(title="Eyes Without a Face")
        doc={"_outcome":"review","candidates":[
            {"provider":"opensubtitles","grade":"review",
             "language":"ja","subtitle_id":"123456",
             "filename":"Les_Yeux_sans_visage_1960-720pJapanese",
             "release_info":"Les Yeux sans visage (1960)","matches":["title"]},
            {"provider":"opensubtitles","grade":"review",
             "language":"ja","subtitle_id":"234567",
             "filename":"Unrelated.1998.ja.srt","matches":["title"]},
        ]}
        with patch.object(saved.stage,"identity_ok",return_value=False):
            jobs,counts,samples=saved.saved_work(
                [row],staged=set(),rejected=set(),review_only=True,
                scope="movies-horror",search_reader=lambda _:doc)
        self.assertEqual(jobs,[])
        self.assertEqual(counts["review_releases_saved"],2)
        self.assertEqual(counts["review_releases_identity_unverified"],2)
        self.assertEqual(counts["review_titles_missing_jellyfin_original_title"],1)
        self.assertTrue(any("identity_unverified" in sample
                            for sample in samples if isinstance(sample,tuple)))

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
