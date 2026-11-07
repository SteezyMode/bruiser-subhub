"""Offline safety contracts for an unattended, bounded S12 recovery pass."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import subhub_unattended_s12_recovery as u


class UnattendedRecoveryTests(unittest.TestCase):
    def test_expected_source_and_limits_are_bounded(self):
        self.assertEqual((u.SEASON,u.SEARCH_LIMIT), (12,30))
        self.assertLessEqual(u.MAX_STAGING_ALTERNATES,2)
        self.assertTrue(u.SERIES.startswith("It's Always Sunny"))

    def test_exact_ten_episode_identity(self):
        good={
            f"{i:032x}":{"jellyfin_id":f"{i:032x}",
              "kind":"Episode","series_title":u.SERIES,"season":12,
              "episode":i,"host_path":f"/mnt/BigDisk/S12E{i:02d}.mkv"}
            for i in range(1,11)
        }
        stage=mock.Mock()
        stage.read_inventory.return_value=good
        self.assertEqual(len(u.season_inventory(stage)),10)
        stage.read_inventory.return_value={k:v for k,v in good.items() if v["episode"]!=10}
        with self.assertRaisesRegex(RuntimeError,"not_exact_ten"):
            u.season_inventory(stage)

    def test_retry_does_not_claim_publish_on_held(self):
        inventory={"a"*32:{"episode":1}}
        publisher=mock.Mock()
        publisher.choose.side_effect=RuntimeError("trusted_timing_gate_hold")
        got=u.retry_publish(publisher,{"a"*32:[("1111","sha")]},inventory)
        self.assertEqual(len(got),1)
        publisher.publish_selected.assert_not_called()
        publisher.mark_completed.assert_not_called()

    def test_success_uses_native_create_only_publisher(self):
        jid="b"*32
        publisher=mock.Mock()
        publisher.choose.return_value=("ready_ffsubsync",{},{"existing_gates":True})
        remaining=u.retry_publish(publisher,{jid:[("1111","sha")]},
                                  {jid:{"episode":7}})
        self.assertEqual(remaining,{})
        publisher.publish_selected.assert_called_once()
        publisher.mark_completed.assert_called_once_with(jid)

    def test_no_alternates_does_not_call_provider(self):
        jid="c"*32
        stage=mock.Mock()
        stage.read_saved_searches.return_value=[(jid,json.dumps({"candidates":[]}))]
        stage.read_staged.return_value=set()
        context=mock.MagicMock()
        stage.stage_db.return_value=context
        new,limited=u.alternative_stage(stage,
            {jid:{"status":"ready_ja_search","episode":5}}, {jid:[("1111","sha")]})
        self.assertEqual((new,limited),(0,False))
        stage.run_one.assert_not_called()

    def test_automatic_source_handoff_honors_existing_one_time_budget(self):
        auto=mock.Mock()
        auto.next_run_budget.return_value=(25,True)
        process=mock.Mock(returncode=0,stdout="inactive\n",stderr="")
        with mock.patch.object(u.subprocess,"run",return_value=process) as run:
            u.start_existing_automatic_source(auto)
        auto.set_next_run_budget.assert_not_called()
        self.assertTrue(any("bruiser-ja-source-autofill.service" in call.args[0]
                            for call in run.call_args_list))

    def test_automatic_source_handoff_creates_one_time_budget_only_if_missing(self):
        auto=mock.Mock()
        auto.next_run_budget.return_value=(600,False)
        process=mock.Mock(returncode=0,stdout="inactive\n",stderr="")
        with mock.patch.object(u.subprocess,"run",return_value=process):
            u.start_existing_automatic_source(auto)
        auto.set_next_run_budget.assert_called_once_with(45)

    def test_recovery_releases_source_lock_before_starting_normal_service(self):
        auto=mock.Mock()
        auto.lock.return_value=14
        auto.config.return_value={}
        auto.native_search_disabled.return_value=True
        with mock.patch.object(u,"modules",return_value=(
            auto,mock.Mock(),mock.Mock(),mock.Mock())),\
            mock.patch.object(u,"check_services"),\
            mock.patch.object(u,"season_inventory",return_value={}),\
            mock.patch.object(u,"held_candidates",return_value={}),\
            mock.patch.object(u,"retry_publish",return_value={}),\
            mock.patch.object(u,"alternative_stage",return_value=(0,False)),\
            mock.patch.object(u,"reconcile"),\
            mock.patch.object(u,"start_existing_automatic_source") as start,\
            mock.patch.object(u.os,"close") as close:
            def verify(_):
                close.assert_called_once_with(14)
            start.side_effect=verify
            self.assertEqual(u.run(),0)

    def test_provider_limit_prevents_broad_search_start(self):
        auto=mock.Mock()
        auto.lock.return_value=14
        auto.config.return_value={}
        auto.native_search_disabled.return_value=True
        with mock.patch.object(u,"modules",return_value=(
            auto,mock.Mock(),mock.Mock(),mock.Mock())),\
            mock.patch.object(u,"check_services"),\
            mock.patch.object(u,"season_inventory",return_value={}),\
            mock.patch.object(u,"held_candidates",return_value={}),\
            mock.patch.object(u,"retry_publish",return_value={}),\
            mock.patch.object(u,"alternative_stage",return_value=(0,True)),\
            mock.patch.object(u,"reconcile"),\
            mock.patch.object(u,"start_existing_automatic_source") as start,\
            mock.patch.object(u.os,"close"):
            self.assertEqual(u.run(),0)
            start.assert_not_called()


if __name__=="__main__":
    unittest.main()
