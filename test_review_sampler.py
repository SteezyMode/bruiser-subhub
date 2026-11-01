"""Offline synthetic fixtures for read-only editorial QA sampling."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import review_sampler as review
import service as s


def source(n):
    return ('\n\n'.join(f'{i}\n00:00:{i//60:02d},{i%60:03d} --> 00:00:{i//60:02d},{i%60:03d}\nEnglish text {i}' for i in range(1, n+1))+'\n').encode()


class EditorialReviewTests(unittest.TestCase):
    def test_mechanical_flags_are_advisory(self):
        row = {'english': '<i>No, I paid 47 dollars.</i>', 'japanese': 'はい、四十七ドルです。',
               'start_ms': 0, 'end_ms': 8000}
        flags = review.flag_cue(row, {})
        self.assertIn('formatting_review', flags)
        self.assertIn('number_review', flags)
        self.assertIn('negation_review', flags)
        self.assertNotIn('missing_japanese', flags)

    def test_sampling_spreads_across_movie(self):
        cues = [{'cue_id': i} for i in range(100)]
        flags = [[] for _ in cues]
        ids = review.pick_indices(cues, flags, 15)
        self.assertEqual(len(ids), 15)
        self.assertEqual(ids[0], 0)
        self.assertEqual(ids[-1], 99)

    def test_risky_cue_prioritized(self):
        cues = [{'cue_id': i} for i in range(100)]
        flags = [[] for _ in cues]
        flags[47] = ['missing_japanese']
        self.assertIn(47, review.pick_indices(cues, flags, 8))

    def test_read_only_packet_keeps_queue_and_state_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            st = s.Store(root)
            data = (b'1\n00:00:01,000 --> 00:00:03,000\nI paid 12 dollars.\n\n'
                    b'2\n00:00:04,000 --> 00:00:06,000\nNo, I did not!\n')
            st.add('test-movie', root/'movie.mkv', data, 'eng')
            st.record_japanese('test-movie', {'1': '12ドル払った。', '2': '違う！'})
            before = st.cn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            packet = review.make_packet(root/'jobs.sqlite3', 'test-movie', count=2)
            after = st.cn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            self.assertEqual(before, after)
            self.assertEqual(packet['selected_cues'], 2)
            self.assertEqual(packet['translated_cues'], 2)
            self.assertNotIn('video', json.dumps(packet))
            self.assertEqual(packet['entries'][0]['english_context'][0]['cue_id'], 2)
            self.assertEqual(packet['entries'][1]['english_context'][0]['cue_id'], 1)
            st.cn.close()

    def test_unknown_job_does_not_create_state(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                review.make_packet(Path(temp)/'jobs.sqlite3', 'not-there')
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_cli_summary_has_no_text_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            st = s.Store(root)
            st.add('test-movie', root/'movie.mkv',
                   b'1\n00:00:01,000 --> 00:00:03,000\nPrivate film dialogue.\n', 'eng')
            st.cn.close()
            result = subprocess.run([sys.executable, str(Path(review.__file__)),
                '--root', str(root), '--job', 'test-movie'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('Private film dialogue', result.stdout)
            self.assertTrue((root / 'jobs.sqlite3').exists())
            self.assertFalse((root / 'review').exists())

    def test_english_only_flags_missing_and_hy_not_required(self):
        r={'english':'Run!', 'japanese':None,'start_ms':0,'end_ms':1000}
        self.assertEqual(review.flag_cue(r,{}),['missing_japanese'])


if __name__ == '__main__':
    unittest.main()
