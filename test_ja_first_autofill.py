"""Source-only host timer: mock API, systemd and local catalog; never touch user services."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tools import ja_first_autofill as auto


def settings(interval=24):
    return {
        "wanted_search_interval_hours":interval,
        "wanted_search_on_startup":False,
        "target_language":"ja","provider_budget_enabled":True,
        "wanted_auto_translate":False,"translation_enabled":False,
        "webhook_auto_translate":False,"jellyfin_play_translate_enabled":False,
        "subtitle_automation_enabled":False,"upgrade_enabled":False,
    }


class SourceAutofillTests(unittest.TestCase):
    def test_config_accepts_only_safe_sources_and_native_off(self):
        safe=settings(0)
        auto.safe_source_settings(safe)
        self.assertTrue(auto.native_search_disabled(safe))
        notsafe=settings(24)
        self.assertFalse(auto.native_search_disabled(notsafe))
        notsafe["wanted_auto_translate"]=True
        with self.assertRaisesRegex(RuntimeError,"automatic_ai"):
            auto.safe_source_settings(notsafe)

    def test_native_search_must_be_off_before_any_provider_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            with patch.object(auto,"ROOT",Path(tmp)):
                with patch.object(auto,"ensure_installed"):
                    with patch.object(auto,"config",return_value=settings(24)):
                        with patch.object(auto,"refresh_manifest",
                                          side_effect=lambda **kw:calls.append("refresh")):
                            with self.assertRaisesRegex(RuntimeError,"duplicate_provider"):
                                auto.once(request=lambda *a,**k:{"is_searching":False})
            self.assertEqual(calls,[])

    def test_once_uses_refresh_then_only_no_ai_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            class Dummy:
                returncode=0
            with patch.object(auto,"ROOT",Path(tmp)), \
                 patch.object(auto,"ensure_installed"), \
                 patch.object(auto,"config",return_value=settings(0)), \
                 patch.object(auto,"refresh_manifest",
                              side_effect=lambda **kw:calls.append("refresh")), \
                 patch.object(auto.subprocess,"run",
                              side_effect=lambda args,**kw:calls.append(args) or Dummy()):
                auto.once(request=lambda endpoint,*args:{"is_searching":False})
            self.assertEqual(calls[0],"refresh")
            cmd=calls[1]
            self.assertIn("--sources-only",cmd)
            self.assertNotIn("start-worker",cmd)
            self.assertEqual(cmd[cmd.index("--search-budget")+1],"600")
            self.assertEqual(cmd[cmd.index("--stage-budget")+1],"200")
            self.assertEqual(cmd[cmd.index("--publish-limit")+1],"200")

    def test_manual_once_bounds_all_stages_without_persisting_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            class Dummy:
                returncode=0
            with patch.object(auto,"ROOT",Path(tmp)), \
                 patch.object(auto,"ensure_installed"), \
                 patch.object(auto,"config",return_value=settings(0)), \
                 patch.object(auto,"selected_source_scope",return_value="movies-no-anime"), \
                 patch.object(auto,"refresh_manifest"), \
                 patch.object(auto.subprocess,"run",
                              side_effect=lambda args,**kw:calls.append(args) or Dummy()):
                auto.once(request=lambda endpoint,*args:{"is_searching":False},
                          search_budget=12,stage_budget=8,publish_limit=15,
                          scope="all")
            self.assertEqual(len(calls),1)
            cmd=calls[0]
            self.assertEqual(cmd[cmd.index("--search-budget")+1],"12")
            self.assertEqual(cmd[cmd.index("--stage-budget")+1],"8")
            self.assertEqual(cmd[cmd.index("--publish-limit")+1],"15")
            self.assertEqual(cmd[cmd.index("--scope")+1],"all")
            self.assertIn("--sources-only",cmd)
            self.assertNotIn("start-worker",cmd)

    def test_manual_once_rejects_oversized_or_zero_budgets_before_side_effects(self):
        for override in ({"search_budget":601},{"stage_budget":201},
                         {"publish_limit":201},{"search_budget":0},
                         {"stage_budget":0},{"publish_limit":0},
                         {"scope":"invalid"}):
            with patch.object(auto,"ensure_installed") as check:
                with self.assertRaises(RuntimeError):
                    auto.once(**override)
                check.assert_not_called()

    def test_explicit_manual_search_does_not_consume_saved_scheduled_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/"next-budget.json"
            with patch.object(auto,"ROOT",root), \
                 patch.object(auto,"NEXT_BUDGET_FILE",path):
                auto.set_next_run_budget(45)
                class Dummy:
                    returncode=0
                with patch.object(auto,"ensure_installed"), \
                     patch.object(auto,"config",return_value=settings(0)), \
                     patch.object(auto,"refresh_manifest"), \
                     patch.object(auto.subprocess,"run",return_value=Dummy()):
                    auto.once(request=lambda endpoint,*args:{"is_searching":False},
                              search_budget=10,stage_budget=2,publish_limit=2)
                self.assertEqual(auto.next_run_budget(),(45,True))

    def test_enable_creates_only_own_units_and_hands_off_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            control=base/"control"
            control.mkdir()
            (control/"ja_first_autofill.py").write_text("# stub\n")
            units=base/"units"
            state=settings(24)
            calls=[]
            def request(endpoint,payload=None):
                if payload is None:
                    return state.copy() if endpoint.endswith("/config") else {"is_searching":False}
                calls.append(("config",payload))
                state.update(payload)
                return {"status":"saved"}
            def action(cmd,**kw):
                calls.append(tuple(cmd))
                return "active\n"
            with patch.object(auto,"CODE",control), \
                 patch.object(auto,"USER_UNITS",units), \
                 patch.object(auto,"ensure_installed"), \
                 patch.object(auto,"refresh_manifest"):
                auto.enable(request=request,action=action)
            self.assertTrue((units/auto.NAME).exists())
            self.assertTrue((units/auto.SVC).exists())
            self.assertEqual(state["wanted_search_interval_hours"],0)
            self.assertIn(("systemctl","--user","enable","--now",auto.NAME),calls)
            self.assertTrue(auto.native_search_disabled(state))
            self.assertNotIn("start-worker",(units/auto.SVC).read_text())
            self.assertIn("ja_first_autofill.py once --apply",
                          (units/auto.SVC).read_text())

    def test_failed_enable_restores_original_native_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            control=base/"control"
            control.mkdir()
            (control/"ja_first_autofill.py").write_text("# stub\n")
            state=settings(24)
            changed=[]
            def request(endpoint,payload=None):
                if payload is None:
                    return state.copy() if endpoint.endswith("/config") else {"is_searching":False}
                state.update(payload)
                changed.append(payload.copy())
                return {"status":"saved"}
            def action(cmd,**kw):
                if "enable" in cmd:
                    raise RuntimeError("systemd_enable_failed")
                return "ok"
            with patch.object(auto,"CODE",control), \
                 patch.object(auto,"USER_UNITS",base/"units"), \
                 patch.object(auto,"ensure_installed"), \
                 patch.object(auto,"refresh_manifest"):
                with self.assertRaisesRegex(RuntimeError,"systemd_enable_failed"):
                    auto.enable(request=request,action=action)
            self.assertEqual(state["wanted_search_interval_hours"],24)
            self.assertEqual(changed[-1]["wanted_search_interval_hours"],24)

    def test_preexisting_group_writable_systemd_directory_is_hardened(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            unit_dir=root/"systemd"/"user"
            unit_dir.mkdir(parents=True)
            unrelated=unit_dir/"existing.service"
            unrelated.write_text("original unit content")
            unit_dir.chmod(0o775)
            with patch.object(auto,"USER_UNITS",unit_dir):
                auto.unit_file(auto.NAME,auto.TIMER)
            self.assertEqual(unit_dir.stat().st_mode&0o777,0o700)
            self.assertEqual(unrelated.read_text(),"original unit content")
            self.assertEqual((unit_dir/auto.NAME).read_text(),auto.TIMER)

    def test_foreign_owned_systemd_directory_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit_dir=Path(tmp)/"user"
            unit_dir.mkdir()
            unit_dir.chmod(0o775)
            with patch.object(auto,"USER_UNITS",unit_dir), \
                 patch.object(auto.os,"getuid",return_value=unit_dir.stat().st_uid+1):
                with self.assertRaisesRegex(RuntimeError,"not_owned"):
                    auto.unit_file(auto.NAME,auto.TIMER)
            self.assertEqual(unit_dir.stat().st_mode&0o777,0o775)
            self.assertFalse((unit_dir/auto.NAME).exists())

    def test_symlinked_user_systemd_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            target=base/"actual"
            target.mkdir()
            link=base/"user"
            link.symlink_to(target,target_is_directory=True)
            with patch.object(auto,"USER_UNITS",link):
                with self.assertRaisesRegex(RuntimeError,"is_symlink"):
                    auto.unit_file(auto.NAME,auto.TIMER)
            self.assertEqual(list(target.iterdir()),[])

    def test_only_our_legacy_timer_service_is_migrated_to_eight_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            old=folder/auto.SVC
            old.write_text(auto.LEGACY_SERVICE)
            old.chmod(0o600)
            (folder/"someone-elses.service").write_text("preserved")
            with patch.object(auto,"USER_UNITS",folder):
                auto.unit_file(auto.SVC,auto.SERVICE)
            self.assertIn("TimeoutStartSec=8h",old.read_text())
            self.assertEqual((folder/"someone-elses.service").read_text(),"preserved")
            with patch.object(auto,"USER_UNITS",folder):
                with self.assertRaisesRegex(RuntimeError,"different_existing"):
                    auto.unit_file(auto.SVC,"unrecognized contents")

    def test_quota_reset_schedule_and_guarded_legacy_timer_migration(self):
        self.assertIn('OnCalendar=*-*-* 09:15:00', auto.TIMER)
        self.assertIn('OnCalendar=*-*-* 05:15:00', auto.LEGACY_TIMER)
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            old=base/auto.NAME
            old.write_text(auto.LEGACY_TIMER)
            old.chmod(0o600)
            foreign=base/"unrelated.timer"
            foreign.write_text("unchanged")
            with patch.object(auto,"USER_UNITS",base):
                auto.unit_file(auto.NAME,auto.TIMER)
                self.assertEqual(old.read_text(),auto.TIMER)
                self.assertEqual(foreign.read_text(),"unchanged")
                with self.assertRaisesRegex(RuntimeError,"different_existing"):
                    auto.unit_file(auto.NAME,"foreign timer contents")

    def test_one_time_budget_is_private_and_consumed_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            budget=root/".next-budget.json"
            with patch.object(auto,"ROOT",root), \
                 patch.object(auto,"NEXT_BUDGET_FILE",budget):
                auto.set_next_run_budget(75)
                self.assertEqual(auto.next_run_budget(),(75,True))
                self.assertEqual(budget.stat().st_mode&0o777,0o600)
                calls=[]
                class Dummy:
                    returncode=0
                with patch.object(auto,"ensure_installed"), \
                     patch.object(auto,"config",return_value=settings(0)), \
                     patch.object(auto,"refresh_manifest"), \
                     patch.object(auto.subprocess,"run",
                         side_effect=lambda args,**kw:calls.append(args) or Dummy()):
                    auto.once(request=lambda endpoint,*args:{"is_searching":False})
                self.assertEqual(calls[0][calls[0].index("--search-budget")+1],"75")
                self.assertEqual(auto.next_run_budget(),(600,False))
                self.assertFalse(budget.exists())

    def test_interrupted_one_time_budget_is_reused_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            budget=root/".next-budget.json"
            with patch.object(auto,"ROOT",root), \
                 patch.object(auto,"NEXT_BUDGET_FILE",budget):
                auto.set_next_run_budget(50)
                class Failed:
                    returncode=1
                with patch.object(auto,"ensure_installed"), \
                     patch.object(auto,"config",return_value=settings(0)), \
                     patch.object(auto,"refresh_manifest"), \
                     patch.object(auto.subprocess,"run",return_value=Failed()):
                    with self.assertRaisesRegex(RuntimeError,"sources_only_cycle_failed"):
                        auto.once(request=lambda endpoint,*args:{"is_searching":False})
                self.assertEqual(auto.next_run_budget(),(50,True))

    def test_one_time_budget_rejects_symlinks_and_invalid_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            budget=root/".next-budget.json"
            victim=root/"unrelated"
            victim.write_text("do not touch")
            budget.symlink_to(victim)
            with patch.object(auto,"ROOT",root), \
                 patch.object(auto,"NEXT_BUDGET_FILE",budget):
                with self.assertRaisesRegex(RuntimeError,"is_symlink"):
                    auto.set_next_run_budget(80)
                with self.assertRaisesRegex(RuntimeError,"outside_1_to_600"):
                    auto.set_next_run_budget(601)
            self.assertEqual(victim.read_text(),"do not touch")

    def test_unit_file_does_not_replace_unexpected_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(auto,"USER_UNITS",Path(tmp)):
                auto.unit_file(auto.NAME,auto.TIMER)
                auto.unit_file(auto.NAME,auto.TIMER)
                with self.assertRaisesRegex(RuntimeError,"overwrite"):
                    auto.unit_file(auto.NAME,"not our timer")


if __name__=="__main__":
    unittest.main()
