"""Synthetic-only regression tests for Benchmark 003; Ollama is mocked."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import benchmark_model_card_003 as t
from tools import model_benchmark as m


class CardBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)/'pilot'
        self.root=self.base/'subhub1-state'
        self.base.mkdir()
        db=service.Store(self.root)
        src=('\n\n'.join(
            f"{i}\n00:{i//60:02d}:{i%60:02d},000 --> "
            f"00:{(i+1)//60:02d}:{(i+1)%60:02d},000\n"
            f"Invented scene {i}."
            for i in range(1,500))+'\n').encode()
        self.digest=hashlib.sha256(src).hexdigest()
        db.add(m.JOB_ID,self.base/'fictional.mkv',src,'eng')
        db.record_japanese(m.JOB_ID,{'35':'既存の翻訳。'})
        db.state(m.JOB_ID,'published')
        db.cn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def groups(self):
        with patch.object(m,'SOURCE_SHA',self.digest):
            return t.preflight(self.root,{t.MODEL:t.MODEL_ID})

    def test_card_prompt_is_minimal_and_one_previous_pair(self):
        row={'cue_id':12,'english':'Synthetic original.'}
        prior={'cue_id':11,'english':'Prior source.',
               'candidate_japanese':'前の翻訳。','end_ms':1000,'clean':True}
        self.assertNotIn('adult horror',t.SYSTEM)
        self.assertIn('STYLE: neutral.',t.SYSTEM)
        self.assertIn('Preserve meaning, tone, slang, profanity',t.SYSTEM)
        p=t.messages(row,prior)
        self.assertIn('[CURRENT_SOURCE]\nSynthetic original.',p[1]['content'])
        self.assertIn('[PREVIOUS_SOURCE]\nPrior source.',p[1]['content'])
        self.assertIn('[PREVIOUS_TRANSLATION]\n前の翻訳。',p[1]['content'])
        self.assertEqual(p[0]['content'],t.SYSTEM)
        self.assertEqual(t.messages(row)[1]['content'],'[CURRENT_SOURCE]\nSynthetic original.')

    def test_gap_only_factor_changes_arm_and_never_crosses_windows(self):
        row={'cue_id':12,'english':'text','start_ms':12000}
        prior={'cue_id':11,'english':'previous','end_ms':1000,
               'candidate_japanese':'翻訳。','clean':True}
        self.assertIsNotNone(t.context_for(prior,row,'card_previous'))
        self.assertIsNone(t.context_for(prior,row,'card_previous_gap8'))
        row['start_ms']=9000
        self.assertIsNotNone(t.context_for(prior,row,'card_previous_gap8'))
        prior['clean']=False
        self.assertIsNone(t.context_for(prior,row,'card_previous'))
        prior['clean']=True
        prior['cue_id']=10
        self.assertIsNone(t.context_for(prior,row,'card_previous'))
        self.assertEqual(t.GAP_LIMIT_SECONDS,8.0)

    def test_exact_source_model_and_options_are_pinned(self):
        with patch.object(m,'SOURCE_SHA',self.digest):
            groups=t.preflight(self.root,{t.MODEL:t.MODEL_ID})
        self.assertEqual(len(groups),8)
        self.assertEqual(sum(map(len,groups)),64)
        with self.assertRaisesRegex(ValueError,'Installed model ID mismatch'):
            t.preflight(self.root,{t.MODEL:'another-digest'})
        with self.assertRaisesRegex(ValueError,'source SHA changed'):
            t.preflight(self.root,{t.MODEL:t.MODEL_ID})
        self.assertEqual(t.OPTIONS,{'temperature':0,'num_ctx':1344,'num_predict':256})

    def test_both_arms_same_64_cues_and_no_checkpoint_edit(self):
        groups=self.groups()
        captured=[]
        def fake_call(model,messages):
            self.assertEqual(model,t.MODEL)
            captured.append(messages)
            self.assertNotIn('既存の翻訳。',str(messages))
            return 'いいね。'
        before=(self.root/'jobs.sqlite3').stat().st_size
        results,calls,reason=t.run_arms(self.base,self.root,groups,call=fake_call)
        self.assertIsNone(reason)
        self.assertEqual(len(results),128)
        self.assertEqual(len(calls),128)
        self.assertEqual(len(captured),128)
        for arm in t.ARMS:
            subset=[r for r in results if r['arm']==arm]
            self.assertEqual([r['cue_id'] for r in subset],
                             [cue['cue_id'] for window in groups for cue in window])
            self.assertEqual(sum(r['valid_japanese'] for r in subset),64)
            self.assertEqual(sum(bool(r['structural_flags']) for r in subset),0)
            self.assertEqual(subset[0]['context_cue_id'],None)
            self.assertEqual(subset[1]['context_cue_id'],31)
            self.assertEqual(subset[8]['context_cue_id'],None)
        self.assertEqual((self.root/'jobs.sqlite3').stat().st_size,before)
        job,dbrows=m.get_rows(self.root,m.JOB_ID)
        self.assertEqual(job['status'],'published')
        self.assertEqual(dbrows[34]['japanese'],'既存の翻訳。')
        self.assertTrue(all('NOT SCORED' in x['semantic_quality']
                            for x in t.overview(results,calls)))

    def test_generation_options_and_no_answer_cleanup(self):
        captured=[]
        class Response:
            def __init__(self,payload):self.payload=payload
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def read(self,*a):return json.dumps(self.payload).encode()
        def opener(req,timeout=120):
            captured.append(json.loads(req.data))
            return Response({'message':{'content':'  テスト？」,  '}})
        result=t.query(t.MODEL,[{'role':'user','content':'synthetic'}],opener=opener)
        self.assertEqual(result,'テスト？」,')
        self.assertEqual(captured[0]['options'],t.OPTIONS)
        self.assertEqual(captured[0]['think'],False)
        self.assertEqual(captured[0]['stream'],False)

    def test_failed_response_does_not_enter_next_context(self):
        groups=self.groups()[:1]
        index=[0]
        def failing(model,msg):
            index[0]+=1
            return '変な文字？」,' if index[0]==2 else '自然な字幕。'
        outputs,calls,stopped=t.run_arms(self.base,self.root,groups,call=failing)
        self.assertIsNone(stopped)
        self.assertEqual(len(outputs),16)
        # Normal arm is first in the first window.
        arm=[r for r in outputs if r['arm']=='card_previous']
        self.assertTrue(arm[1]['structural_flags'])
        self.assertIsNone(arm[2]['context_cue_id'])
        self.assertNotIn('変な文字？」,',str(t.messages(
            {'english':'test','cue_id':8})))

if __name__=='__main__':
    unittest.main()
