"""Synthetic tests for a frozen, safe local 2x2 translation experiment."""
import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import service
from tools import model_benchmark as m


class ModelBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)/'pilot'
        self.root=self.base/'subhub1-state'
        self.base.mkdir()
        db=service.Store(self.root)
        source=('\n\n'.join(
            f"{i}\n00:{i//60:02d}:{i%60:02d},000 --> 00:{(i+1)//60:02d}:{(i+1)%60:02d},000\n"
            f"Sample dialogue {i}."
            for i in range(1,500))+'\n').encode()
        self.source_sha=hashlib.sha256(source).hexdigest()
        db.add(m.JOB_ID,self.base/'movie.mkv',source,'eng')
        db.record_japanese(m.JOB_ID,{'35':'古い日本語の字幕。'})
        db.state(m.JOB_ID,'translated')
        db.cn.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_model_inventory_is_verified_and_unambiguous(self):
        found={'gemma4:e4b-it-qat':'digestA',
               '17slever17/translate-gemma-4-sub:e4b':'digestB'}
        self.assertEqual(m.resolve_models(found,'gemma4:e4b-it-qat','auto'),
                         ('gemma4:e4b-it-qat','17slever17/translate-gemma-4-sub:e4b'))
        with self.assertRaisesRegex(ValueError,'not installed'):
            m.resolve_models(found,'missing','auto')
        found['some-other/translate-gemma-4-sub:e4b']='digestC'
        with self.assertRaisesRegex(ValueError,'exactly one'):
            m.resolve_models(found,'gemma4:e4b-it-qat','auto')
        with self.assertRaisesRegex(ValueError,'different model IDs'):
            m.resolve_models(found,'gemma4:e4b-it-qat','gemma4:e4b-it-qat')

    def test_ollama_model_digest_inventory_from_official_cli_format(self):
        output=('NAME                                        ID            SIZE     MODIFIED\n'
                'gemma4:e4b-it-qat                          abc123        5.5 GB   2 days ago\n'
                '17slever17/translate-gemma-4-sub:e4b      def456        3 GB     2 hours ago\n')
        fake=lambda *a,**kw:types.SimpleNamespace(returncode=0,stdout=output)
        self.assertEqual(m.installed_models(fake),{
            'gemma4:e4b-it-qat':'abc123',
            '17slever17/translate-gemma-4-sub:e4b':'def456'})

    def test_frozen_source_windows_and_sha_are_checked(self):
        with patch.object(m,'SOURCE_SHA',self.source_sha):
            job,windows=m.checked_windows(self.root)
        self.assertEqual(job['id'],m.JOB_ID)
        self.assertEqual(len(windows),8)
        self.assertEqual(sum(len(x) for x in windows),64)
        self.assertEqual([x[4]['cue_id'] for x in windows],list(m.CENTERS))
        with self.assertRaisesRegex(ValueError,'source SHA changed'):
            m.checked_windows(self.root)

    def test_all_four_arms_use_exactly_the_same_64_cues_without_db_writes(self):
        seen=[]
        def fake_call(base,rows,memory,model,style):
            seen.append((model,style,tuple(r['cue_id'] for r in rows)))
            return {str(r['cue_id']):'どうしたの？' for r in rows}
        with patch.object(m,'SOURCE_SHA',self.source_sha):
            _,windows=m.checked_windows(self.root)
        before=(self.root/'jobs.sqlite3').stat().st_size
        models=('gemma4:e4b-it-qat','17slever17/translate-gemma-4-sub:e4b')
        result,calls,stop=m.evaluate(self.base,self.root,models,windows,
                                     translator=fake_call,max_seconds=300)
        self.assertIsNone(stop)
        self.assertEqual(len(result),256)
        self.assertEqual(len(calls),32)
        self.assertEqual(len(seen),32)
        for model in models:
            for style in m.STYLES:
                ids=[x['cue_id'] for x in result
                     if x['model']==model and x['style']==style]
                self.assertEqual(ids,[r['cue_id'] for g in windows for r in g])
        metrics=m.metrics(result,calls,models)
        self.assertEqual(len(metrics),4)
        self.assertTrue(all(x['valid_cues']==64 for x in metrics))
        self.assertTrue(all('NOT SCORED' in x['semantic_quality'] for x in metrics))
        self.assertEqual((self.root/'jobs.sqlite3').stat().st_size,before)
        db=service.Store(self.root)
        self.assertEqual(db.rows(m.JOB_ID)[34]['japanese'],'古い日本語の字幕。')
        self.assertEqual(db.jobs()[0]['status'],'translated')
        db.cn.close()

    def test_output_is_private_and_create_only(self):
        from tools.benchmark_localization import save_private
        path=self.base/'blind-comparison.json'
        save_private(path,{'copyrighted_cue':'synthetic private'})
        with self.assertRaises(FileExistsError):
            save_private(path,{'overwrite':True})
        self.assertIn('synthetic private',path.read_text())


if __name__=='__main__':
    unittest.main()
