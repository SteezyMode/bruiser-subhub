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
            self.assertEqual(cmd[cmd.index("--stage-budget")+1],"2")

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
            link.symlink_to(target,directory=True)
            with patch.object(auto,"USER_UNITS",link):
                with self.assertRaisesRegex(RuntimeError,"is_symlink"):
                    auto.unit_file(auto.NAME,auto.TIMER)
            self.assertEqual(list(target.iterdir()),[])

    def test_unit_file_does_not_replace_unexpected_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(auto,"USER_UNITS",Path(tmp)):
                auto.unit_file(auto.NAME,auto.TIMER)
                auto.unit_file(auto.NAME,auto.TIMER)
                with self.assertRaisesRegex(RuntimeError,"overwrite"):
                    auto.unit_file(auto.NAME,"not our timer")


if __name__=="__main__":
    unittest.main()
