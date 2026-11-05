"""Offline safety tests: one actual dry-run search, no publications or config writes."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock

from tools import sublarr_japanese_dryrun_pilot as pilot


def wanted_row(id, path, language="ja", status="wanted", subtitle_type="full"):
    return dict(id=id, file_path=str(path), target_language=language,
                status=status, subtitle_type=subtitle_type,
                search_count=0)


class TestSublarrJapaneseDryrun(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        self.video = self.tmp / "American.Dad.S19E16.mkv"
        self.video.write_bytes(b"movie-header")

    def fake_get(self, rows, gate="ok", auto_translate=False, upgrade=False):
        def get(path):
            if path == "/api/v1/providers/health":
                return {"providers":[{"name":"opensubtitles","enabled":True,
                                      "initialized":True,"gate":gate}]}
            if path == "/api/v1/config":
                return {"wanted_auto_translate":auto_translate,
                        "upgrade_enabled":upgrade}
            if path.startswith("/api/v1/wanted?"):
                return {"data":rows,"total":len(rows)}
            self.fail("Unexpected GET "+path)
        return get

    def test_one_ja_full_item_only_one_post(self):
        rows = [
            wanted_row(1,self.video,language="en"),
            wanted_row(2,self.video,language="ja",status="ignored"),
            wanted_row(3,self.video),
        ]
        posts = []
        def post(path, body):
            posts.append((path,body))
            return {"results":[{"wanted_id":3,"status":"not_found",
                                "dry_run":True}]}
        with unittest.mock.patch.object(pilot.os.path,"islink",return_value=False):
            out = pilot.run(self.fake_get(rows),post,is_file=lambda p:True,
                            allowed_roots=(str(self.tmp)+"/",))
        self.assertEqual(len(posts),1)
        self.assertEqual(posts[0][1],{"item_ids":[3]})
        self.assertEqual(posts[0][0],"/api/v1/wanted/dry-run")
        self.assertTrue(out["dry_run"])

    def test_existing_original_ja_sidecar_skipped(self):
        (self.tmp / "American.Dad.S19E16.ja.srt").write_text("日本語")
        rows=[wanted_row(3,self.video)]
        post=Mock()
        with unittest.mock.patch.object(pilot.os.path,"islink",return_value=False):
            out = pilot.run(self.fake_get(rows),post,is_file=lambda p:True,
                          allowed_roots=(str(self.tmp)+"/",))
        self.assertIsNone(out)
        post.assert_not_called()

    def test_existing_bruiser_ja_sidecar_skipped(self):
        (self.tmp / "American.Dad.S19E16.Bruiser Japanese.ja.srt").write_text("日本語")
        rows=[wanted_row(3,self.video)]
        post=Mock()
        with unittest.mock.patch.object(pilot.os.path,"islink",return_value=False):
            out = pilot.run(self.fake_get(rows),post,is_file=lambda p:True,
                            allowed_roots=(str(self.tmp)+"/",))
        self.assertIsNone(out)
        post.assert_not_called()

    def test_wrong_or_forced_language_and_invalid_paths_not_eligible(self):
        candidates=[
            wanted_row(1,self.video,language="en"),
            wanted_row(2,self.video,subtitle_type="forced"),
            wanted_row(3,self.video,language="ja",status="failed"),
            wanted_row(4,"/not/media/test.mkv"),
        ]
        response={"data":candidates,"total":4}
        result,seen,total = pilot.find_one_wanted(
            lambda _:response,is_file=lambda _:True,
            allowed_roots=(str(self.tmp)+"/",)
        )
        self.assertIsNone(result)
        self.assertEqual(seen,4)

    def test_fails_loudly_on_wrong_wanted_json_shape(self):
        # Regression: former code read "items" and silently showed zero,
        # while Sublarr 1.18 actually returns the list as "data".
        with self.assertRaisesRegex(RuntimeError, 'expected "data" list'):
            pilot.find_one_wanted(lambda _:{"items":[wanted_row(1,self.video)],
                                            "total":1},
                                  allowed_roots=(str(self.tmp)+"/",))

    def test_search_refused_when_api_gate_blocked(self):
        post=Mock()
        with self.assertRaisesRegex(RuntimeError,"not ready"):
            pilot.run(self.fake_get([],gate="no_pool_key"),post)
        post.assert_not_called()

    def test_search_refused_if_auto_translate_or_upgrades_enabled(self):
        for value in ((True,False),(False,True)):
            with self.subTest(value=value):
                post=Mock()
                with self.assertRaisesRegex(RuntimeError,"safety"):
                    pilot.run(self.fake_get([],auto_translate=value[0],
                                            upgrade=value[1]),post)
                post.assert_not_called()

    def test_invalid_or_duplicate_response_holds(self):
        post=lambda p, d:{"results":[{"wanted_id":999,"status":"found"}]}
        with unittest.mock.patch.object(pilot.os.path,"islink",return_value=False):
            with self.assertRaisesRegex(RuntimeError,"Unexpected"):
                pilot.run(self.fake_get([wanted_row(3,self.video)]),
                          post,is_file=lambda p:True,
                          allowed_roots=(str(self.tmp)+"/",))


if __name__=="__main__":
    unittest.main()
