"""Synthetic tests for source-checked, checkpoint-preserving local cue repairs."""
import fcntl
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
import service as s

SPEC=importlib.util.spec_from_file_location('recover_cues_helper',Path(__file__).parent/'tools/recover_cues.py')
R=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(R)


class RecoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)/'bruiser-pilot'
        self.root=self.base/'subhub1-state'
        self.db=s.Store(self.root)
        source=b'1\n00:00:01,000 --> 00:00:02,000\nA.\n\n2\n00:00:03,000 --> 00:00:04,000\nB.\n\n3\n00:00:05,000 --> 00:00:06,000\nThree, two...\n'
        self.db.add('example',self.base/'sample.mkv',source,'eng')
        self.db.record_japanese('example',{'1':'ア。'})
        self.manifest={'schema':'bruiser-private-cue-fixes-v1','edits':[
            {'job_id':'example','cue_id':1,'english':'A.','previous_japanese':'ア。','japanese':'エー。'},
            {'job_id':'example','cue_id':2,'english':'B.','previous_japanese':None,'japanese':'ビー。'},
            {'job_id':'example','cue_id':3,'english':'Three, two...','previous_japanese':None,'japanese':'３、２…'}]}

    def tearDown(self):
        self.db.cn.close();self.tmp.cleanup()

    def test_japanese_exception_validator_is_narrow(self):
        yes=[('RC！','RC!'),('B.','B.'),('３、２…','Three, two...'),('救急隊！','EMS!')]
        no=[('EMS!','EMS!'),('I O.D.','I O.D.'),('3, 2...','We die in three or two days.'),
            ('I am sorry.','I am sorry.'),('3, 2...','Four, five...')]
        for ja,en in yes:self.assertTrue(s.acceptable_ja(ja,en),(ja,en))
        for ja,en in no:self.assertFalse(s.acceptable_ja(ja,en),(ja,en))
        self.assertFalse(s.acceptable_ja('RC！'))

    def test_approve_three_exact_cues_backup_and_preserve_old_checkpoints(self):
        before=self.db.cn.execute('SELECT english,timing FROM cues ORDER BY cue_id').fetchall()
        verified=R.verified_corrections(self.db,self.manifest,s)
        R.apply(self.db,verified,s,self.root,publish=False)
        rows=self.db.rows('example')
        self.assertEqual([r['japanese'] for r in rows],['エー。','ビー。','３、２…'])
        self.assertEqual([tuple(x) for x in before],[(r['english'],r['timing']) for r in rows])
        self.assertEqual(self.db.jobs()[0]['status'],'translated')
        backups=list((self.root/'backups').glob('manual-cue-repair-*.sqlite3'))
        self.assertEqual(len(backups),1)
        with sqlite3.connect(backups[0]) as backup:
            self.assertEqual(backup.execute('SELECT japanese FROM cues WHERE cue_id=2').fetchone()[0],None)

    def test_stale_source_or_previous_ja_aborts_untouched(self):
        self.manifest['edits'][0]['previous_japanese']='not the current JP'
        with self.assertRaisesRegex(RuntimeError,'Japanese cue changed'):
            R.verified_corrections(self.db,self.manifest,s)
        self.assertEqual(self.db.rows('example')[0]['japanese'],'ア。')
        self.assertFalse((self.root/'backups').exists())

    def test_no_published_job_edited(self):
        self.db.state('example','published')
        with self.assertRaisesRegex(RuntimeError,'already published'):
            R.verified_corrections(self.db,self.manifest,s)

    def test_worker_lock_prevents_parallel_edits(self):
        p=self.root/'run.lock';h=p.open('a+b')
        fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            with self.assertRaisesRegex(RuntimeError,'Worker active'):
                with R.worker_locks(self.base,self.root):pass
        finally:fcntl.flock(h,fcntl.LOCK_UN);h.close()


if __name__=='__main__':unittest.main()
