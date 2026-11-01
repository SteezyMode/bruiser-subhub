"""Synthetic tests for true native single-segment subtitle model evaluation."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import benchmark_native_subtitles as n
from tools import model_benchmark as m


class NativeSubtitleBenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)/'pilot'
        self.root=self.base/'subhub1-state'
        self.base.mkdir()
        store=service.Store(self.root)
        source=('\n\n'.join(
            f"{i}\n00:{i//60:02d}:{i%60:02d},000 --> "
            f"00:{(i+1)//60:02d}:{(i+1)%60:02d},000\n"
            f"Synthetic dialogue {i}."
            for i in range(1,500))+'\n').encode()
        self.source_sha=hashlib.sha256(source).hexdigest()
        store.add(m.JOB_ID,self.base/'fictional.mkv',source,'eng')
        store.record_japanese(m.JOB_ID,{'35':'歴史的な字幕。'})
        store.state(m.JOB_ID,'published')
        store.cn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def frozen_groups(self):
        with patch.object(m,'SOURCE_SHA',self.source_sha):
            return m.checked_windows(self.root)[1]

    def test_model_card_uses_exact_current_only(self):
        current={'english':'English now.'}
        history=[
            {'cue_id':1,'english':'Earlier line 1.','candidate_japanese':'先に一つ。'},
            {'cue_id':2,'english':'Earlier line 2.','candidate_japanese':'先に二つ。'},
            {'cue_id':3,'english':'Earlier line 3.','candidate_japanese':'先に三つ。'},
        ]
        messages=n.native_messages(current,history)
        self.assertEqual(len(messages),2)
        self.assertIn('Translate only CURRENT_SOURCE',messages[0]['content'])
        prompt=messages[1]['content']
        self.assertIn('[PREVIOUS_SOURCE]\nEarlier line 2.\nEarlier line 3.',prompt)
        self.assertNotIn('Earlier line 1.',prompt)
        self.assertIn('[PREVIOUS_TRANSLATION]\n先に二つ。\n先に三つ。',prompt)
        self.assertIn('[CURRENT_SOURCE]\nEnglish now.',prompt)
        self.assertNotIn('歴史的な字幕。',prompt)
        self.assertEqual(n.native_messages(current,[])[1]['content'],
                         '[CURRENT_SOURCE]\nEnglish now.')

    def test_preflight_pins_existing_model_digest_and_english_source(self):
        with patch.object(m,'SOURCE_SHA',self.source_sha):
            _,groups=n.preflight(self.root,{n.MODEL:n.MODEL_ID})
        self.assertEqual(len(groups),8)
        self.assertEqual(sum(len(g) for g in groups),64)
        with patch.object(m,'SOURCE_SHA',self.source_sha):
            with self.assertRaisesRegex(ValueError,'Frozen subtitle model'):
                n.preflight(self.root,{n.MODEL:'new-digest'})
        with self.assertRaisesRegex(ValueError,'source SHA changed'):
            n.preflight(self.root,{n.MODEL:n.MODEL_ID})

    def test_all_64_cues_sequential_context_generated_only_in_same_window(self):
        calls=[]
        def fake_call(model,messages,timeout=120):
            self.assertEqual(model,n.MODEL)
            calls.append(messages)
            return '翻訳した字幕。'
        groups=self.frozen_groups()
        before=(self.root/'jobs.sqlite3').stat().st_size
        rows,attempts,stopped=n.run_calls(self.base,self.root,groups,call=fake_call)
        self.assertIsNone(stopped)
        self.assertEqual(len(rows),64)
        self.assertEqual(len(attempts),64)
        self.assertTrue(all(r['valid_japanese'] for r in rows))
        self.assertTrue(all(not r['structural_flags'] for r in rows))
        self.assertEqual(rows[0]['previous_successful_context_cues'],[])
        self.assertEqual(rows[1]['previous_successful_context_cues'],[31])
        self.assertEqual(rows[2]['previous_successful_context_cues'],[31,32])
        self.assertEqual(rows[8]['previous_successful_context_cues'],[])
        self.assertEqual(rows[4]['historical_japanese'],'歴史的な字幕。')
        self.assertNotIn('歴史的な字幕。',str(calls))
        self.assertEqual((self.root/'jobs.sqlite3').stat().st_size,before)
        job,_=m.get_rows(self.root,m.JOB_ID) if hasattr(m,'get_rows') else (None,None)
        self.assertIsNotNone(job)
        self.assertEqual(job['status'],'published')
        self.assertEqual(n.summary(rows,attempts)['valid_japanese'],64)

    def test_bad_model_response_does_not_poison_following_context(self):
        groups=[self.frozen_groups()[0]]
        seq=[0]
        def fake_call(model,messages,timeout=120):
            seq[0]+=1
            if seq[0]==2:return 'あ？」,'
            return '正しい字幕だ。'
        rows,attempts,stopped=n.run_calls(self.base,self.root,groups,call=fake_call)
        self.assertIsNone(stopped)
        self.assertEqual(rows[1]['structural_flags'],['unmatched_japanese_quote',
                                                       'serialized_object_fragment'])
        self.assertEqual(rows[2]['previous_successful_context_cues'],[31])
        self.assertNotIn('あ？」,',rows[2]['candidate_japanese'])

    def test_native_reply_parsing_rejects_truncation_and_empty(self):
        class Response:
            def __init__(self,data):self.data=data
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def read(self,*a):return __import__('json').dumps(self.data).encode()
        def opener_with(data):
            return lambda *a,**kw:Response(data)
        self.assertEqual(n.native_call(n.MODEL,[{'role':'user','content':'test'}],
                                       opener=opener_with({'message':{'content':'うん。'}})),'うん。')
        with self.assertRaisesRegex(ValueError,'truncated'):
            n.native_call(n.MODEL,[],opener=opener_with({'done_reason':'length','message':{'content':'...'}}))
        with self.assertRaisesRegex(ValueError,'Empty'):
            n.native_call(n.MODEL,[],opener=opener_with({'message':{'content':''}}))

    def test_native_summary_reports_quality_as_unscored(self):
        result=n.summary([{'cue_id':3,'valid_japanese':True,'structural_flags':[],
                           'chars_per_second':8.2}],
                         [{'seconds':1.2,'error':None}])
        self.assertIn('NOT SCORED',result['semantic_quality'])
        self.assertEqual(result['model_call_seconds'],1.2)


if __name__=='__main__':
    unittest.main()
