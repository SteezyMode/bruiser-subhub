"""Offline SQL fixtures for strictly read-only metadata inventory 006."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.inventory_sources_006 import inventory, EXCLUDED_SHA


class SourceInventory006Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.db=self.root/'jobs.sqlite3'
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""
                CREATE TABLE jobs (
                  id TEXT PRIMARY KEY, source_sha TEXT NOT NULL,
                  source_cues INT, status TEXT, audio_lang TEXT, scope TEXT
                );
                CREATE TABLE cues (
                  job_id TEXT, cue_id INT, english TEXT,
                  start_ms INT, end_ms INT
                );
            """)
            known=next(iter(EXCLUDED_SHA))
            for jid,source,n in (
                ('notorious-old-benchmark', known,70),
                ('first-new-title','a'*64,88),
                ('second-new-title','b'*64,80),
                ('short-test-title','c'*64,4),
            ):
                conn.execute(
                    'INSERT INTO jobs(id,source_sha,source_cues,status,audio_lang,scope)'
                    ' VALUES(?,?,?,?,?,?)',(jid,source,n,'translated','eng','horror'))
                conn.executemany(
                    'INSERT INTO cues(job_id,cue_id,english,start_ms,end_ms)'
                    ' VALUES(?,?,?,?,?)',
                    ((jid,i,'PRIVATE ENGLISH DO NOT PRINT',
                       i*15_000,i*15_000+1000) for i in range(n))
                )

    def tearDown(self):
        self.temp.cleanup()

    def test_metadata_only_and_prior_sha_exclusion(self):
        before=self.db.read_bytes()
        data=inventory(self.root)
        self.assertEqual(data['total_jobs'],4)
        self.assertEqual(data['eligible_count'],2)
        self.assertEqual(data['excluded_known_source_count'],1)
        jobs={r['job_id']:r for r in data['jobs']}
        self.assertEqual(jobs['notorious-old-benchmark']['exclusion_reason'],
                         'prior_benchmark_source')
        self.assertIsNone(jobs['first-new-title']['exclusion_reason'])
        self.assertEqual(jobs['short-test-title']['exclusion_reason'],
                         'not_enough_english_cues')
        self.assertNotIn('PRIVATE ENGLISH',str(data))
        self.assertNotIn('video',str(data).lower())
        self.assertEqual(self.db.read_bytes(),before)

    def test_owner_exclusions_are_immutable_and_metadata_only(self):
        data=inventory(self.root,exclusions=['a'*64])
        self.assertEqual(data['eligible_count'],1)
        self.assertEqual(data['excluded_known_source_count'],2)
        self.assertTrue(data['read_only'])

    def test_minimums_are_frozen_and_no_source_mutation(self):
        data=inventory(self.root,min_cues=4,min_span_min=0)
        self.assertEqual(data['eligible_count'],3)
        with self.assertRaises(FileNotFoundError):
            inventory(Path(self.temp.name)/'no-such-state')

if __name__=='__main__':
    unittest.main()
