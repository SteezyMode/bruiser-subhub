"""Offline tests for runnable 006: fresh title freeze, resumable private outputs, blind SRT."""
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools import clean_sweep_006 as s


class Clean006Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'state'
        self.root.mkdir()
        self.out=Path(self.temp.name)/'private-test'
        self.db=self.root/'jobs.sqlite3'
        with sqlite3.connect(self.db) as cn:
            cn.executescript("""
            CREATE TABLE jobs (
              id TEXT PRIMARY KEY, source_sha TEXT NOT NULL,
              status TEXT, audio_lang TEXT, scope TEXT
            );
            CREATE TABLE cues (
              job_id TEXT NOT NULL,cue_id INT NOT NULL,
              english TEXT NOT NULL,timing TEXT NOT NULL,
              start_ms INT NOT NULL,end_ms INT NOT NULL
            );""")
            for j in range(6):
                name='film-'+str(j)
                source=s.OLD_SHA if j==0 else f'{j:064x}'
                cn.execute('INSERT INTO jobs VALUES (?,?,?,?,?)',
                           (name,source,'published','eng','horror'))
                cn.executemany(
                    'INSERT INTO cues VALUES (?,?,?,?,?,?)',
                    ((name,i,'Invented dialogue '+str(i),
                     '00:01:00,000 --> 00:01:02,000',
                     i*8000,i*8000+1800) for i in range(800))
                )
        self.original=self.db.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_corpus_deterministic_source_hash_and_reserve(self):
        sources=s.fetch_sources(self.root)
        self.assertEqual(len(sources),5)
        a,holdout=s.choose_scenes(sources,'synthetic-seed')
        b,holdout2=s.choose_scenes(sources,'synthetic-seed')
        self.assertEqual(s.digest(a),s.digest(b))
        self.assertEqual(holdout,holdout2)
        self.assertTrue(4<=len(a)<=6)
        self.assertGreaterEqual(sum(len(x['cues']) for x in a),200)
        self.assertEqual(len(set(x['job_id'] for x in a)),3)
        self.assertNotIn(holdout['job_id'],set(x['job_id'] for x in a))
        self.assertNotIn('film-0',str(a))
        self.assertEqual(self.db.read_bytes(),self.original)

    def test_frozen_manifest_one_time_and_detects_sqlite_mutation(self):
        result=s.prepare(self.root,self.out)
        same=s.prepare(self.root,self.out)
        self.assertEqual(result,same)
        self.assertEqual(result['manifest_sha256'],s.digest(result['payload']))
        self.assertNotIn('film-0',str(result))
        s.verify_sources(result['payload'],self.root)
        with sqlite3.connect(self.db) as cn:
            chosen=result['payload']['scenes'][0]['job_id']
            cue=result['payload']['scenes'][0]['cues'][0]['cue_id']
            cn.execute("UPDATE cues SET english='CHANGED' WHERE job_id=? AND cue_id=?",
                       (chosen,cue))
        with self.assertRaisesRegex(RuntimeError,'Frozen English/timing cue changed'):
            s.verify_sources(result['payload'],self.root)

    def test_registered_candidates_and_correct_prompt_types(self):
        self.assertEqual(len(s.ROSTER),10)
        self.assertEqual(s.ROSTER['hy18'][1],
                         'hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M')
        self.assertEqual(s.ROSTER['index2'][0],'index')
        self.assertEqual(s.ROSTER['cat7'][1],'cyberagent/CAT-Translate-7b')
        self.assertEqual(s.ROSTER['tuned_e4b'][0],'native')
        self.assertEqual(s.ROSTER['generic_e4b'][0],'native')
        self.assertEqual(s.ROSTER['cat33'][0],'hf')
        self.assertEqual(s.ROSTER['google12'][0],'google')

    def test_two_completed_arms_generate_actual_srt_and_private_key(self):
        manifest=s.prepare(self.root,self.out)
        scenes=manifest['payload']['scenes']
        for arm in ('tuned_e4b','hy7'):
            for scene in scenes:
                for cue in scene['cues']:
                    s.store_exclusive(
                        s.record_path(self.out,arm,scene['scene_id'],cue['cue_id']),
                        {'manifest_sha256':manifest['manifest_sha256'],
                         'cue_id':cue['cue_id'],
                         'scene_id':scene['scene_id'],
                         'candidate_japanese':'これは人工の日本語です。',
                         'valid_japanese':True,'flags':[],'error':None})
        self.assertEqual(s.blind(self.out),0)
        self.assertEqual(s.blind(self.out),0)
        blind=self.out/'blind'
        key=json.loads((blind/'IDENTITY_KEY_PRIVATE.json').read_text())
        self.assertEqual(set(key['mapping']),set(x['scene_id'] for x in scenes))
        self.assertEqual(set(key['mapping']['s01']),{'A','B'})
        first=(blind/'s01'/'option_A.srt')
        self.assertTrue(first.exists())
        self.assertIn('00:01:00,000 --> 00:01:02,000',first.read_text())
        self.assertIn('これは人工の日本語です。',first.read_text())
        self.assertFalse((blind/'s01'/'option_A.srt.json').exists())
        self.assertTrue((blind/'REVIEW_SCORES_PRIVATE.csv').exists())
        self.assertTrue(s.summarize(self.out)['tuned_e4b']['complete'])

    def test_blind_excludes_blocked_results(self):
        manifest=s.prepare(self.root,self.out)
        scenes=manifest['payload']['scenes']
        for arm in ('cat7','google4'):
            for scene in scenes:
                for cue in scene['cues']:
                    s.store_exclusive(
                        s.record_path(self.out,arm,scene['scene_id'],cue['cue_id']),
                        {'manifest_sha256':manifest['manifest_sha256'],
                         'cue_id':cue['cue_id'],'scene_id':scene['scene_id'],
                         'candidate_japanese':'日本語。','valid_japanese':True})
        s.store_exclusive(self.out/'arms'/'cat7'/'blocked.json',
                          {'reason':'invalid chat template'})
        self.assertEqual(s.blind(self.out),1)
        self.assertFalse((self.out/'blind'/'IDENTITY_KEY_PRIVATE.json').exists())

if __name__=='__main__':
    unittest.main()
