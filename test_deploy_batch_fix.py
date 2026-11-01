"""Synthetic no-SSH tests for guarded subtitle engine source deployment."""
import fcntl
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import service as s

SPEC=importlib.util.spec_from_file_location('deploy_helper',Path(__file__).parent/'tools/deploy_batch_fix.py')
helper=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class DeployTests(unittest.TestCase):
    def fixture(self):
        tmp=tempfile.TemporaryDirectory()
        base=Path(tmp.name)/'bruiser-pilot'
        (base/'subhub1').mkdir(parents=True)
        live=base/'subhub1/service.py'
        live.write_text('print("original")\n')
        candidate=base/'subhub1/service.candidate.py'
        shutil.copy2(Path(s.__file__),candidate)
        root=base/'subhub1-state'
        db=s.Store(root)
        db.add('example',base/'film.mkv',
               b'1\n00:00:01,000 --> 00:00:02,000\nI know!\n\n'
               b'2\n00:00:02,000 --> 00:00:03,000\nNo!\n','eng')
        db.cn.close()
        helper.EXPECTED_UNPATCHED=helper.hash_file(live)
        fake=types.ModuleType('bruiser_auto')
        fake.parse_srt=lambda f:[types.SimpleNamespace(id=r[0],text=r[4])
                                 for r in s.parse_srt(Path(f).read_bytes())]
        return tmp,base,root,live,candidate,fake

    def test_validates_real_rows_and_installs_without_changing_db(self):
        tmp,base,root,live,candidate,fake=self.fixture()
        try:
            old=b'print("original")\n'
            dbhash=helper.hash_file(root/'jobs.sqlite3')
            with patch.dict(sys.modules,{'bruiser_auto':fake}):
                helper.install(candidate,live,root,base)
            self.assertEqual(live.read_bytes(),Path(s.__file__).read_bytes())
            self.assertFalse(candidate.exists())
            self.assertEqual(next(live.parent.glob('service.py.before-batchfix-*')).read_bytes(),old)
            self.assertEqual(helper.hash_file(root/'jobs.sqlite3'),dbhash)
        finally:tmp.cleanup()

    def test_worker_lock_prevents_source_swap(self):
        tmp,base,root,live,candidate,fake=self.fixture()
        try:
            handle=(root/'run.lock').open('a+b')
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:
                with patch.dict(sys.modules,{'bruiser_auto':fake}):
                    with self.assertRaisesRegex(RuntimeError,'ACTIVE WORKER'):
                        helper.install(candidate,live,root,base)
            finally:
                fcntl.flock(handle,fcntl.LOCK_UN)
                handle.close()
            self.assertEqual(live.read_text(),'print("original")\n')
            self.assertTrue(candidate.exists())
        finally:tmp.cleanup()

if __name__=='__main__':unittest.main()
