"""Scope-completion preview tests: no providers, media writes, or GPU."""
import unittest
from unittest import mock
from tools import subhub_finish_scope as finish


class ScopeCompletionTests(unittest.TestCase):
    def test_select_all_or_one_season(self):
        catalog=[{"series":"It's Always Sunny in Philadelphia",
                  "seasons":[1,2,9]}]
        with mock.patch.object(finish.batch,"catalog",return_value=catalog):
            self.assertEqual(finish.scope_seasons(
                "It's Always Sunny in Philadelphia"),[1,2,9])
            self.assertEqual(finish.scope_seasons(
                "It's Always Sunny in Philadelphia",[9]),[9])
            with self.assertRaisesRegex(ValueError,"selected_season"):
                finish.scope_seasons("It's Always Sunny in Philadelphia",[10])

    def test_scope_skips_covered_preserves_japanese_repair_and_rejects_duplicates(self):
        def report(series,season):
            if season==1:
                return {"items":[
                    {"episode":1,"status":"covered"},
                    {"episode":2,"status":"ready","can_translate":True,
                     "search":{"plausible_candidates":0}},
                    {"episode":3,"status":"review","can_translate":False,
                     "reason":"duplicate_episode_versions"},
                    {"episode":4,"status":"review","can_translate":True,
                     "search":{"plausible_candidates":2}},
                    {"episode":5,"status":"review","can_translate":True,
                     "search":{"plausible_candidates":2},
                     "failed_source_qa":True}]}
            return {"items":[{"episode":1,"status":"covered"}]}
        with mock.patch.object(finish,"scope_seasons",return_value=[1,9]), \
             mock.patch.object(finish.batch,"season_report",side_effect=report):
            result=finish.plan("It's Always Sunny in Philadelphia",[1,9])
        self.assertEqual(result["total"],6)
        self.assertEqual(result["covered"],2)
        self.assertEqual(result["missing"],4)
        self.assertEqual(result["duplicate_versions"],1)
        self.assertEqual(result["plamo_ready"],2)
        self.assertEqual(result["picks"],[
            {"season":1,"episode":2},{"season":1,"episode":5}])

    def test_source_failure_does_not_proceed_to_translation(self):
        plan={"series":"Sunny","seasons":[9],"total":10,"covered":3,
              "missing":7,"source_first":7,"plamo_ready":0,
              "duplicate_versions":1,"picks":[]}
        with mock.patch.object(finish,"plan",return_value=plan), \
             mock.patch.object(finish,"write_state") as saved, \
             mock.patch.object(finish,"command",return_value=1) as command:
            self.assertEqual(finish.run("Sunny",[9]),1)
            self.assertEqual(command.call_count,1)
            self.assertEqual(saved.call_args.args[0]["state"],"held")


if __name__=="__main__":
    unittest.main()
