"""Systemd user timer install safety; no real systemctl invocations."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tools import enable_american_dad_timer as timer


class NightlyAutoTimerTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home=Path(tmp.name)

    def test_timer_is_owner_only_non_destructive_and_low_priority(self):
        commands=[]
        def fake(cmd,**kwargs):
            commands.append(cmd)
            return SimpleNamespace(returncode=0)
        self.assertTrue(timer.enable(self.home,runner=fake,log=lambda *x:None))
        root=self.home/'.config/systemd/user'
        service=(root/(timer.UNIT+'.service')).read_text()
        task=(root/(timer.UNIT+'.timer')).read_text()
        self.assertIn('american_dad_maintenance.py',service)
        self.assertIn('Nice=15',service)
        self.assertIn('CPUQuota=250%',service)
        self.assertIn('MemoryMax=5G',service)
        self.assertIn('RuntimeMaxSec=11h',service)
        self.assertIn('ExecStart=/usr/bin/python3 -u ',service)
        self.assertIn('Type=exec',service)
        self.assertIn('KillMode=control-group',service)
        self.assertIn('OnCalendar=*-*-* 04:30:00',task)
        self.assertIn('Persistent=true',task)
        self.assertNotIn('apt ',service)
        self.assertNotIn('sublarr',service.lower())
        self.assertNotIn('jellyfin',task.lower())
        self.assertEqual(commands[-1],[
            'systemctl','--user','is-active',timer.UNIT+'.timer'])
        self.assertTrue(timer.enable(self.home,runner=fake,log=lambda *x:None))

    def test_known_deployed_oneshot_is_upgraded_without_losing_timer(self):
        folder=self.home/'.config/systemd/user'
        folder.mkdir(parents=True)
        service=folder/(timer.UNIT+'.service')
        configured_timer=folder/(timer.UNIT+'.timer')
        service.write_text(timer.LEGACY_SERVICE,encoding='utf8')
        configured_timer.write_text(timer.TIMER,encoding='utf8')
        events=[]
        def runner(cmd,**kwargs):
            events.append(cmd)
            return SimpleNamespace(returncode=0)
        self.assertTrue(timer.enable(self.home,runner=runner,
                                     log=lambda *x:None))
        upgraded=service.read_text()
        self.assertEqual(upgraded,timer.SERVICE)
        self.assertIn('ExecStart=/usr/bin/python3 -u ',upgraded)
        self.assertIn('Type=exec',upgraded)
        self.assertIn('RuntimeMaxSec=11h',upgraded)
        self.assertIn('KillMode=control-group',upgraded)
        self.assertNotIn('TimeoutStartSec=120min',upgraded)
        self.assertEqual(configured_timer.read_text(),timer.TIMER)
        backup=folder/(timer.UNIT+'.service.before-supervised.bak')
        self.assertEqual(backup.read_text(),timer.LEGACY_SERVICE)
        self.assertEqual(events[0],['systemctl','--user','daemon-reload'])
        self.assertTrue(timer.enable(self.home,runner=runner,
                                     log=lambda *x:None))
        self.assertEqual(backup.read_text(),timer.LEGACY_SERVICE)

    def test_migration_rejects_changed_backup_without_modifying_service(self):
        folder=self.home/'.config/systemd/user'
        folder.mkdir(parents=True)
        service=folder/(timer.UNIT+'.service')
        service.write_text(timer.LEGACY_SERVICE)
        backup=folder/(timer.UNIT+'.service.before-supervised.bak')
        backup.write_text('do not overwrite this unrelated backup')
        with self.assertRaisesRegex(RuntimeError,'backup differs'):
            timer.enable(self.home,runner=lambda *a,**k:None)
        self.assertEqual(service.read_text(),timer.LEGACY_SERVICE)
        self.assertEqual(backup.read_text(),
                         'do not overwrite this unrelated backup')

    def test_protect_custom_unit(self):
        folder=self.home/'.config/systemd/user'
        folder.mkdir(parents=True)
        service=folder/(timer.UNIT+'.service')
        service.write_text('custom user unit')
        with self.assertRaisesRegex(RuntimeError,'overwritten'):
            timer.enable(self.home,runner=lambda *a,**k:None)
        self.assertEqual(service.read_text(),'custom user unit')

    def test_symlink_refusal(self):
        folder=self.home/'.config/systemd/user'
        folder.mkdir(parents=True)
        outside=self.home/'outside'
        outside.write_text('private')
        (folder/(timer.UNIT+'.timer')).symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError,'symlink'):
            timer.enable(self.home,runner=lambda *a,**k:None)
        self.assertEqual(outside.read_text(),'private')

    def test_service_requires_active_user_bus(self):
        actions=[]
        def failed(cmd,**kwargs):
            actions.append(cmd)
            return SimpleNamespace(returncode=1)
        self.assertFalse(timer.enable(self.home,runner=failed,
                                      log=lambda *x:None))
        self.assertEqual(len(actions),1)


if __name__=='__main__':
    unittest.main()
