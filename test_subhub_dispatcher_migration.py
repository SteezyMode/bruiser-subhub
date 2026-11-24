"""Test migration of existing timers without invoking systemd."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock
from tools import install_global_ja_sourcing as installer


class MigrationTests(unittest.TestCase):
    def simulate(self, failure=False):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)
            host=home/"code"
            units=home/"units"
            backup=home/"backup"
            for p in (host,units,backup,home/".local/bin"):
                p.mkdir(parents=True,mode=0o700)
            worker=host/"subhub_auto.py"
            worker.write_text("worker")
            ai=home/".local/bin/subhub-ai"
            ai.write_text("ai")
            ai.chmod(0o700)
            timers={x:{"enabled":True,"active":True} for x in (
                installer.SOURCE_TIMER,"subhub-household.timer",
                "subhub-bulk-publisher.timer")}
            original=dict([(installer.SOURCE_UNIT,"ja_first_autofill.py"),
                           ("subhub-household.service","subhub_household.py")])
            def ctl(*args,**kwargs):
                action,name=args[:2] if len(args)>1 else (args[0],None)
                if action=="is-enabled":
                    value=timers[name]["enabled"]
                    return SimpleNamespace(returncode=0 if value else 1,
                                           stdout="enabled" if value else "disabled")
                if action=="is-active":
                    value=timers.get(name,{}).get("active",False)
                    return SimpleNamespace(returncode=0 if value else 3,
                                           stdout="active" if value else "inactive")
                if action=="show":
                    override=units/(name+".d")/"30-consolidated-dispatcher.conf"
                    text=original[name]
                    if override.exists() and not (failure and name=="subhub-household.service"):
                        text=override.read_text()
                    return SimpleNamespace(returncode=0,stdout=text)
                if action in ("start","stop"):
                    timers[name]["active"]=action=="start"
                if action in ("enable","disable"):
                    timers[name]["enabled"]=action=="enable"
                return SimpleNamespace(returncode=0,stdout="")
            with mock.patch.object(installer,"HOST",host), \
                 mock.patch.object(installer,"DASH_UNIT_DIR",units), \
                 mock.patch.object(installer.Path,"home",return_value=home), \
                 mock.patch.object(installer,"systemctl",side_effect=ctl):
                if failure:
                    with self.assertRaises(RuntimeError):
                        installer.consolidate_dispatcher(backup)
                else:
                    installer.consolidate_dispatcher(backup)
            self.assertTrue((backup/"dispatcher-timers.json").is_file())
            for name in original:
                override=units/(name+".d")/"30-consolidated-dispatcher.conf"
                self.assertEqual(override.exists(),not failure)
            self.assertTrue(timers[installer.SOURCE_TIMER]["active"])
            self.assertTrue(timers["subhub-household.timer"]["active"])
            self.assertEqual(timers["subhub-bulk-publisher.timer"],
                             {"enabled":failure,"active":failure})

    def test_existing_timers_reused(self):
        self.simulate()

    def test_failed_override_restores_timers(self):
        self.simulate(failure=True)


if __name__=="__main__":
    unittest.main()
