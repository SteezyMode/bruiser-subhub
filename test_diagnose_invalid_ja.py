"""Synthetic tests for read-only publisher validator diagnosis."""
from pathlib import Path
import tempfile
import unittest
import service as s
from tools import diagnose_invalid_ja as diag


class InvalidCuesTests(unittest.TestCase):
    def test_rejects_only_actual_bad_translation_without_db_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            store=s.Store(root)
            store.add('held-film',root/'movie.mkv',
                b'1\n00:00:01,000 --> 00:00:02,000\nHello!\n\n'
                b'2\n00:00:02,000 --> 00:00:03,000\nRC!\n\n'
                b'3\n00:00:03,000 --> 00:00:04,000\nWait!\n', 'eng')
            store.record_japanese('held-film',
                {'1':'こんにちは！','2':'RC！','3':'Wait!'})
            store.state('held-film','publish_hold','Incomplete or malformed Japanese')
            before=store.cn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            job,done,bad=diag.invalid_cues(root/'jobs.sqlite3',s,'held-film')
            self.assertEqual(job['status'],'publish_hold')
            self.assertEqual(done,3)
            self.assertEqual([x['cue_id'] for x in bad],[3])
            self.assertEqual(bad[0]['english'],'Wait!')
            self.assertEqual(bad[0]['japanese'],'Wait!')
            after=store.cn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            self.assertEqual(after,before)
            store.cn.close()

    def test_unknown_job_is_not_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            store=s.Store(root)
            store.cn.close()
            with self.assertRaisesRegex(ValueError,'Unknown job'):
                diag.invalid_cues(root/'jobs.sqlite3',s,'missing-job')


if __name__=='__main__':unittest.main()
