"""Offline nightly English source timer installer tests (no real systemctl)."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tools import enable_english_source_timer as timer


class SourceTimerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)

    def test_created_units_run_only_source_acquisition(self):
        calls=[]
        output=[]
        def fake(cmd,**kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0,stdout='active',stderr='')
        self.assertTrue(timer.setup(self.home,runner=fake,
                                    log=lambda *x:output.append(x)))
        service=(self.home/'.config/systemd/user'/(
            timer.UNIT+'.service')).read_text()
        unit=(self.home/'.config/systemd/user'/(
            timer.UNIT+'.timer')).read_text()
        self.assertIn('library_english_sources.py run --budget 5',service)
        self.assertIn('OnCalendar=*-*-* 03:30:00',unit)
        self.assertIn('Persistent=true',unit)
        self.assertNotIn('american_dad_seasons.py',service)
        self.assertNotIn('daily_worker',service)
        self.assertNotIn('ollama',service)
        self.assertEqual(calls[-1],
                         ['systemctl','--user','is-active',timer.UNIT+'.timer'])
        self.assertEqual(output[-1][0:2],('EN_TIMER','active'))
        self.assertTrue(timer.setup(self.home,runner=fake,
                                    log=lambda *x:None))

    def test_changed_service_or_timer_is_not_clobbered(self):
        unit_dir=self.home/'.config/systemd/user'
        unit_dir.mkdir(parents=True)
        p=unit_dir/(timer.UNIT+'.service')
        p.write_text('# custom existing unit\n')
        calls=[]
        def fake(*args,**kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(RuntimeError,'differs'):
            timer.setup(self.home,runner=fake)
        self.assertEqual(p.read_text(),'# custom existing unit\n')
        self.assertEqual(calls,[])

    def test_symlink_unit_is_refused(self):
        unit_dir=self.home/'.config/systemd/user'
        unit_dir.mkdir(parents=True)
        x=self.home/'outside'
        x.write_text('not yours')
        p=unit_dir/(timer.UNIT+'.service')
        p.symlink_to(x)
        with self.assertRaisesRegex(RuntimeError,'symlinked'):
            timer.setup(self.home,runner=lambda *a,**k:None)
        self.assertEqual(x.read_text(),'not yours')

    def test_no_user_systemd_keeps_file_and_reports_not_active(self):
        logs=[]
        def unavailable(cmd,**kwargs):
            return SimpleNamespace(returncode=1,stderr='no user bus')
        self.assertFalse(timer.setup(
            self.home,runner=unavailable,log=lambda *x:logs.append(x)))
        self.assertEqual(logs[-1][0:2],('EN_TIMER','not_active'))
        self.assertTrue((self.home/'.config/systemd/user'/(
            timer.UNIT+'.timer')).is_file())


if __name__=='__main__':
    unittest.main()
