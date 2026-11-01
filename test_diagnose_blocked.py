"""Synthetic-only tests for blocked-translation read-only diagnostic."""
from pathlib import Path
import tempfile
import unittest
import diagnose_blocked as diag
import service as s


class DiagnosticTests(unittest.TestCase):
    def test_no_database_created(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                diag.blocked(Path(d)/'missing.sqlite3')
            self.assertFalse((Path(d)/'missing.sqlite3').exists())

    def test_exhausted_and_publication_hold_are_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            st=s.Store(root)
            src=(b'1\n00:00:01,000 --> 00:00:02,000\nNever leave.\n\n'
                 b'2\n00:00:03,000 --> 00:00:04,000\nWait.\n')
            st.add('held-movie',root/'movie.mkv',src,'eng')
            for _ in range(5):st.fail('held-movie',[1],'Non-Japanese singleton',terminal=True)
            st.record_japanese('held-movie',{'2':'待って。'})
            st.state('held-movie','needs_review','1 isolated failed cue')
            before=st.cn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            data=diag.blocked(root/'jobs.sqlite3')
            self.assertEqual(len(data),1)
            self.assertEqual(data[0]['exhausted'],1)
            self.assertEqual(data[0]['failed_cues'][0]['id'],1)
            self.assertNotIn('english',data[0]['failed_cues'][0])
            self.assertEqual(st.cn.execute('SELECT COUNT(*) FROM events').fetchone()[0],before)
            self.assertEqual(diag.blocked(root/'jobs.sqlite3',True)[0]['failed_cues'][0]['english'],'Never leave.')
            st.state('held-movie','publish_hold','Existing editorial subtitle')
            data=diag.blocked(root/'jobs.sqlite3')
            self.assertIn('Existing editorial',data[0]['last_error'])
            st.cn.close()

if __name__=='__main__':unittest.main()
