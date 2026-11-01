"""Synthetic-only tests: one exact corrupt-Japanese hold can be recovered safely."""
from pathlib import Path
import importlib.util
import sqlite3
import tempfile
import unittest

import service as s
from tools import scan_checkpoint_contamination as scan

P=Path(__file__).parent/'tools/recover_cues.py'
spec=importlib.util.spec_from_file_location('recover_corrupt_hold',P)
R=importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


class CorruptHoldTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.db=s.Store(self.root)
        source=(b'1\n00:00:01,000 --> 00:00:02,000\n'
                b'- I saw seven or eight.\n- Seven or eight?\n\n'
                b'2\n00:00:03,000 --> 00:00:04,000\nOkay.\n')
        self.db.add('fixture',self.root/'film.mkv',source,'eng')
        self.corrupt='- ７人か８人。/ - ７人か８人？ }'+'<tool_call|>'+chr(96)*3+'json\n{"translations":{}}'
        self.db.record_japanese('fixture',{'1':self.corrupt,'2':'わかった。'})
        self.db.state('fixture','publish_hold','Incomplete or malformed Japanese')
        self.entry={'job_id':'fixture','cue_id':1,
                    'english':'- I saw seven or eight.\n- Seven or eight?',
                    'previous_japanese_prefix':'- ７人か８人。/ - ７人か８人？',
                    'corruption_marker':'<tool_call|>',
                    'japanese':'- ７人か８人見た。\n- ７人か８人？'}
        self.manifest={'schema':'bruiser-private-cue-fixes-v1','edits':[self.entry]}

    def tearDown(self):
        self.db.cn.close()
        self.temp.cleanup()

    def test_source_verified_corrupt_hold_repair_backups_state(self):
        changes=R.verified_corrections(self.db,self.manifest,s)
        self.assertEqual(changes,[('fixture',1,'- ７人か８人見た。\n- ７人か８人？')])
        R.apply(self.db,changes,s,self.root,publish=False)
        self.assertEqual(self.db.rows('fixture')[0]['japanese'],self.entry['japanese'])
        self.assertEqual(self.db.jobs()[0]['status'],'translated')
        backup=list((self.root/'backups').glob('manual-cue-repair-*.sqlite3'))
        self.assertEqual(len(backup),1)
        with sqlite3.connect(backup[0]) as cn:
            self.assertEqual(cn.execute('SELECT japanese FROM cues WHERE cue_id=1').fetchone()[0],self.corrupt)
        self.assertFalse((self.root/'film.Bruiser Japanese.ja.srt').exists())

    def test_wrong_hold_reason_refused_without_mutation(self):
        self.db.state('fixture','publish_hold','Existing approved Bruiser Japanese differs')
        with self.assertRaisesRegex(RuntimeError,'not an invalid-Japanese hold'):
            R.verified_corrections(self.db,self.manifest,s)
        self.assertEqual(self.db.rows('fixture')[0]['japanese'],self.corrupt)

    def test_published_track_never_editable(self):
        self.db.state('fixture','published')
        with self.assertRaisesRegex(RuntimeError,'protected or already published'):
            R.verified_corrections(self.db,self.manifest,s)

    def test_stale_or_missing_corruption_evidence_refused(self):
        self.entry['previous_japanese_prefix']='other text that never existed'
        with self.assertRaisesRegex(RuntimeError,'does not match reviewed corruption'):
            R.verified_corrections(self.db,self.manifest,s)
        self.entry['previous_japanese_prefix']='- ７人か８人。/ - ７人か８人？'
        self.entry.pop('corruption_marker')
        with self.assertRaisesRegex(RuntimeError,'Invalid explicit corrupt-output evidence'):
            R.verified_corrections(self.db,self.manifest,s)

    def test_second_invalid_cue_requires_separate_review(self):
        self.db.cn.execute("UPDATE cues SET japanese='bad English' WHERE job_id='fixture' AND cue_id=2")
        with self.assertRaisesRegex(RuntimeError,'Other invalid cues'):
            R.verified_corrections(self.db,self.manifest,s)

    def test_read_only_scan_finds_machine_output_artifacts(self):
        before=self.db.cn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        results=scan.scan(self.root,s)
        self.assertEqual(len(results),1)
        self.assertEqual(results[0][-2:]],([1],[1]))
        self.assertEqual(self.db.cn.execute('SELECT COUNT(*) FROM events').fetchone()[0],before)

if __name__=='__main__':
    unittest.main()
