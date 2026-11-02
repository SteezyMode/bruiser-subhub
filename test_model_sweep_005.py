"""Offline, synthetic 005 test suite. No local Ollama or media needed."""
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import model_sweep_005 as s
from tools import model_benchmark as m


class Sweep005Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)/'pilot'
        self.root=self.base/'subhub1-state'
        self.base.mkdir(parents=True)
        db=service.Store(self.root)
        source=('\n\n'.join(
            f"{i}\n00:{i//60:02d}:{i%60:02d},000 --> "
            f"00:{(i+1)//60:02d}:{(i+1)%60:02d},000\n"
            f"Invented English {i}."
            for i in range(1,750))+'\n').encode()
        self.digest=hashlib.sha256(source).hexdigest()
        db.add(s.JOB_ID,self.base/'movie.mkv',source,'eng')
        db.record_japanese(s.JOB_ID,{'91':'過去の日本語。'})
        db.state(s.JOB_ID,'published')
        db.cn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def groups(self):
        with patch.object(s,'SOURCE_SHA',self.digest):
            return s.dataset(self.root)

    def test_new_64_cues_exclude_all_old_source_windows(self):
        groups=self.groups()
        self.assertEqual(len(groups),8)
        ids=[r['cue_id'] for g in groups for r in g]
        self.assertEqual(len(ids),64)
        self.assertEqual(len(set(ids)),64)
        self.assertFalse(set(ids)&s.EXCLUDED_IDS)
        self.assertEqual([g[4]['cue_id'] for g in groups],list(s.CENTERS))
        with self.assertRaisesRegex(ValueError,'source SHA changed'):
            s.dataset(self.root)

    def test_native_prompt_for_each_model(self):
        self.assertEqual(s.source_prompt('cat','Hello.'),
                         'Translate the following English text into Japanese.\n\nHello.')
        self.assertIn('only output the translated result',
                      s.source_prompt('hy','Fuck you.'))
        self.assertEqual(s.source_prompt('google','Hello.').split('Japanese:')[1],
                         '\n\n\nHello.')
        with self.assertRaisesRegex(ValueError,'Unknown prompt'):
            s.source_prompt('nonesuch','hello')

    def test_official_parameters_and_one_user_message(self):
        captured=[]
        def post(endpoint,payload,timeout=180):
            captured.append((endpoint,payload))
            return {'message':{'content':'自然な訳。'},
                    'response':'自然な訳。','eval_count':7}
        for key in ('cat7','hy7','google12'):
            value,stats=s.generate(key,'Some made-up dialogue.',[],post=post)
            self.assertEqual(value,'自然な訳。')
            self.assertEqual(stats['eval_count'],7)
        cat=s.FAMILY['cat7']['model']
        self.assertEqual(captured[0][0],'/api/chat')
        self.assertEqual(captured[0][1]['model'],cat)
        self.assertEqual(len(captured[0][1]['messages']),1)
        self.assertEqual(captured[0][1]['options'],s.CAT_OPTIONS)
        self.assertNotIn('temperature',s.CAT_OPTIONS)
        self.assertEqual(captured[1][1]['options']['temperature'],0.7)
        self.assertEqual(captured[1][1]['options']['top_p'],0.6)
        self.assertEqual(captured[1][1]['options']['top_k'],20)
        self.assertEqual(captured[1][1]['options']['repeat_penalty'],1.05)
        self.assertEqual(captured[2][0],'/api/generate')
        self.assertNotIn('messages',captured[2][1])
        self.assertNotIn('temperature',s.GOOGLE_OPTIONS)

    def test_model_details_enforce_expected_quant_and_tuned_digest(self):
        found={spec['model']:'sha-'+key for key,spec in s.FAMILY.items()}
        found[s.SUB_MODEL]=s.SUB_MODEL_ID
        def post(endpoint,payload,timeout=30):
            quant=next(v['quant'] for v in s.FAMILY.values()
                       if v['model']==payload['model'])
            family=('gemma3' if payload['model']=='translategemma:12b' else
                    'gemma4' if payload['model']==s.SUB_MODEL else 'mistral')
            return {'details':{'family':family,
                               'quantization_level':quant,
                               'parameter_size':'7B'},
                    'template':'synthetic template'}
        for key in s.FAMILY:
            item=s.model_metadata(key,found,post=post)
            self.assertEqual(item['quantization'],s.FAMILY[key]['quant'])
            self.assertTrue(item['template_sha256'])
        # Real OptiPlex finding: source GGUF tag says Q4_K_XL,
        # /api/show reports Q4_K_M; the exact pinned ID is unchanged.
        self.assertEqual(s.FAMILY['tuned']['source_tag_quant'],'Q4_K_XL')
        self.assertEqual(s.FAMILY['tuned']['quant'],'Q4_K_M')
        tuned=s.model_metadata('tuned',found,post=post)
        self.assertEqual(tuned['ollama_id'],s.SUB_MODEL_ID)
        self.assertEqual(tuned['family'],'gemma4')
        self.assertEqual(tuned['quantization'],'Q4_K_M')
        self.assertEqual(tuned['source_tag_quant'],'Q4_K_XL')
        def wrong_tuned_family(endpoint,payload,timeout=30):
            x=post(endpoint,payload,timeout)
            x['details']['family']='gemma3'
            return x
        with self.assertRaisesRegex(ValueError,'Wrong model architecture'):
            s.model_metadata('tuned',found,post=wrong_tuned_family)
        def wrong_tuned_quant(endpoint,payload,timeout=30):
            x=post(endpoint,payload,timeout)
            x['details']['quantization_level']='Q8_0'
            return x
        with self.assertRaisesRegex(ValueError,'Quantization mismatch'):
            s.model_metadata('tuned',found,post=wrong_tuned_quant)
        with self.assertRaisesRegex(ValueError,'Not installed'):
            s.model_metadata('hy7',{},post=post)
        with self.assertRaisesRegex(ValueError,'digest changed'):
            s.model_metadata('tuned',{s.SUB_MODEL:'unknown'},post=post)
        def bad_post(*args,**kw):
            return {'details':{'quantization_level':'Q8_0'}}
        with self.assertRaisesRegex(ValueError,'Quantization mismatch'):
            s.model_metadata('cat7',found,post=bad_post)

    def test_per_arm_64_results_with_db_unchanged_and_no_historical_context(self):
        groups=self.groups()
        before=(self.root/'jobs.sqlite3').stat().st_size
        for key in s.FAMILY:
            captured=[]
            def fake_translate(k,english,history):
                self.assertEqual(k,key)
                self.assertNotIn('過去の日本語。',str(history))
                captured.append((english,len(history)))
                return 'それはそうだ。',{'eval_count':4}
            outputs,calls,stop=s.run_one(key,self.base,self.root,groups,
                                        translate=fake_translate)
            self.assertIsNone(stop)
            self.assertEqual(len(outputs),64)
            self.assertEqual(len(calls),64)
            self.assertEqual(s.metrics(outputs,calls)['valid_japanese'],64)
            self.assertEqual(outputs[0]['context_from_cues'],[])
            self.assertEqual(outputs[8]['context_from_cues'],[])
            if key=='tuned':
                self.assertEqual(outputs[1]['context_from_cues'],[groups[0][0]['cue_id']])
            else:
                self.assertTrue(all(not r['context_from_cues'] for r in outputs))
            self.assertEqual(len(captured),64)
        self.assertEqual((self.root/'jobs.sqlite3').stat().st_size,before)
        db=service.Store(self.root)
        self.assertEqual(db.rows(s.JOB_ID)[90]['japanese'],'過去の日本語。')
        self.assertEqual(db.jobs()[0]['status'],'published')
        db.cn.close()

    def test_bad_japanese_and_errors_are_recorded_not_hidden(self):
        groups=self.groups()[:1]
        count=[0]
        def translate(key,english,history):
            count[0]+=1
            if count[0]==1:raise RuntimeError('synthetic gpu error')
            if count[0]==2:return '変な文字？」,',{}
            return '大丈夫。',{}
        outputs,calls,stop=s.run_one('tuned',self.base,self.root,groups,
                                    translate=translate)
        self.assertEqual(len(outputs),8)
        self.assertIn('synthetic gpu error',calls[0]['error'])
        self.assertTrue(outputs[1]['flags'])
        self.assertEqual(outputs[2]['context_from_cues'],[])
        self.assertTrue(all('NOT SCORED' in s.metrics(outputs,calls)['semantic_quality']
                            for _ in range(1)))

if __name__=='__main__':
    unittest.main()
