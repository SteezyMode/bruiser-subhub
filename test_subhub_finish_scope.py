"""One-click scope completion: offline, no provider, GPU or media access."""
import json
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

    def test_source_plan_never_translates_untried_saved_release(self):
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
            output=finish.plan("Sunny",[1,9])
        self.assertEqual(output["total"],6)
        self.assertEqual(output["covered"],2)
        self.assertEqual(output["missing"],4)
        self.assertEqual(output["duplicate_versions"],1)
        self.assertEqual(output["plamo_ready"],2)

    def test_one_action_sources_every_exact_file_and_auto_translates_misses(self):
        first="a"*32
        second="b"*32
        before={"series":"Sunny","seasons":[9],"total":2,
                "missing":2,"covered":0,"picks":[]}
        logs=[]
        def invoke(args,label,on_line=None):
            logs.append((label,[str(x) for x in args]))
            if label.startswith("deep_source_"):
                verdict="covered" if first[:8] in label else "plamo"
                on_line("DEEP_SOURCE_RESULT: "+json.dumps({
                    "result":verdict})+"\n")
            return 0
        with mock.patch.object(finish,"plan",return_value=before), \
             mock.patch.object(finish,"selected_media",
                               return_value=[(9,1,first),(9,2,second)]), \
             mock.patch.object(finish,"initial_covered",return_value=set()), \
             mock.patch.object(finish,"selected_title_metadata",return_value={}), \
             mock.patch.object(finish,"command",side_effect=invoke), \
             mock.patch.object(finish,"valid_source_exhaustion",return_value=True), \
             mock.patch.object(finish,"write_state") as save, \
             mock.patch.object(finish.time,"sleep") as sleep:
            self.assertEqual(finish.run("Sunny",[9]),0)
        self.assertEqual(len(logs),3)
        self.assertEqual([a[0].split("_")[0] for a in logs],
                         ["deep","deep","plamo"])
        self.assertIn("--source-exhausted-auto",logs[2][1])
        self.assertNotIn("--owner-reviewed-source",logs[2][1])
        self.assertEqual(save.call_args.args[0]["covered_exact_files"],2)
        self.assertEqual(save.call_args.args[0]["state"],"completed")
        sleep.assert_not_called()

    def test_quota_defer_remains_source_and_retries_without_human_review(self):
        jid="c"*32
        before={"series":"Sunny","seasons":[9],"total":1,
                "missing":1,"covered":0,"picks":[]}
        calls=[]
        def invoke(args,label,on_line=None):
            calls.append(label)
            outcome="retry_source" if len(calls)==1 else "covered"
            on_line("DEEP_SOURCE_RESULT: "+json.dumps({
                "result":outcome,"reason":"provider_quota"})+"\n")
            return 0
        with mock.patch.object(finish,"plan",return_value=before), \
             mock.patch.object(finish,"selected_media",
                               return_value=[(9,1,jid)]), \
             mock.patch.object(finish,"initial_covered",return_value=set()), \
             mock.patch.object(finish,"selected_title_metadata",return_value={}), \
             mock.patch.object(finish,"command",side_effect=invoke), \
             mock.patch.object(finish,"write_state") as save, \
             mock.patch.object(finish.time,"sleep") as sleep:
            self.assertEqual(finish.run("Sunny",[9]),0)
        self.assertEqual(len(calls),2)
        sleep.assert_called_once_with(7200)
        self.assertEqual(save.call_args.args[0]["state"],"completed")


if __name__=="__main__":
    unittest.main()
