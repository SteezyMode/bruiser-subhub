"""Benchmark 004: official prompt, installed quantization, frozen source, safe holdout."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import benchmark_translategemma_004 as t
from tools import model_benchmark as m


class TranslateGemma004Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)/'pilot'
        self.root=self.base/'subhub1-state'
        self.base.mkdir()
        store=service.Store(self.root)
        src=('\n\n'.join(
            f"{i}\n00:{i//60:02d}:{i%60:02d},000 --> "
            f"00:{(i+1)//60:02d}:{(i+1)%60:02d},000\n"
            f"Invented English line {i}."
            for i in range(1,700))+'\n').encode()
        self.digest=hashlib.sha256(src).hexdigest()
        store.add(t.JOB_ID,self.base/'fictional.mkv',src,'eng')
        store.record_japanese(t.JOB_ID,{'515':'以前の字幕だ。'})
        store.state(t.JOB_ID,'published')
        store.cn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def groups(self):
        with patch.object(m,'SOURCE_SHA',self.digest):
            return t.source_groups(self.root)

    def test_exact_documented_prompt_no_system_or_json_wrapper(self):
        p=t.google_prompt('Do you need help getting laid?')
        self.assertEqual(p,t.PROMPT_HEADER+'\n\n\nDo you need help getting laid?')
        self.assertIn('English (en) to Japanese (ja)',p)
        self.assertIn('Produce only the Japanese translation',p)
        self.assertNotIn('CURRENT_SOURCE',p)
        self.assertNotIn('EXAMPLES',p)
        with self.assertRaisesRegex(ValueError,'Missing English'):
            t.google_prompt(' \n')

    def test_ollama_generate_uses_model_defaults_not_custom_decoding(self):
        calls=[]
        def post(path,data,timeout):
            calls.append((path,data))
            return {'response':'いや、そうじゃない。','done_reason':'stop'}
        self.assertEqual(t.translate_google('No. I did not.',post=post),'いや、そうじゃない。')
        path,request=calls[0]
        self.assertEqual(path,'/api/generate')
        self.assertEqual(request['model'],'translategemma:4b')
        self.assertEqual(request['prompt'],t.google_prompt('No. I did not.'))
        self.assertEqual(request['options'],{'num_ctx':4096,'num_predict':256})
        self.assertNotIn('temperature',request['options'])
        self.assertNotIn('top_k',request['options'])
        self.assertNotIn('top_p',request['options'])
        self.assertNotIn('system',request)
        self.assertNotIn('raw',request)
        self.assertEqual(request['stream'],False)
        with self.assertRaisesRegex(ValueError,'256-token'):
            t.translate_google('synthetic',post=lambda *a,**kw:{
                'response':'...','done_reason':'length'})
        with self.assertRaisesRegex(ValueError,'empty'):
            t.translate_google('synthetic',post=lambda *a,**kw:{'response':'  '})

    def test_model_preflight_checks_correct_official_release_and_family(self):
        found={t.GOOGLE_MODEL:t.GOOGLE_EXPECTED_ID+'rest',
               t.SUB_MODEL:t.SUB_MODEL_ID}
        good={'family':'gemma3','quantization_level':'Q4_K_M'}
        t.full_preflight(found,good)
        with self.assertRaisesRegex(ValueError,'Unexpected official'):
            t.full_preflight({**found,t.GOOGLE_MODEL:'different'},good)
        with self.assertRaisesRegex(ValueError,'Wrong TranslateGemma'):
            t.full_preflight(found,{'family':'gemma4','quantization_level':'Q4_K_M'})
        with self.assertRaisesRegex(ValueError,'Wrong TranslateGemma'):
            t.full_preflight(found,{'family':'gemma3','quantization_level':'Q8_0'})
        with self.assertRaisesRegex(ValueError,'subtitle model missing'):
            t.full_preflight({t.GOOGLE_MODEL:t.GOOGLE_EXPECTED_ID},good)
        with self.assertRaisesRegex(ValueError,'Explicitly install'):
            t.full_preflight({t.SUB_MODEL:t.SUB_MODEL_ID},good)

    def test_source_is_frozen_with_64_prior_and_16_new_cues(self):
        anchors,holdout=self.groups()
        self.assertEqual(sum(len(g) for g in anchors),64)
        self.assertEqual(sum(len(g) for g in holdout),16)
        self.assertEqual([g[4]['cue_id'] for g in holdout],list(t.HOLDOUT_CENTERS))
        prior={r['cue_id'] for g in anchors for r in g}
        new={r['cue_id'] for g in holdout for r in g}
        self.assertFalse(prior & new)
        with self.assertRaisesRegex(ValueError,'source SHA changed'):
            t.source_groups(self.root)

    def test_96_outputs_are_genuine_fresh_model_native_and_db_unchanged(self):
        anchors,holdout=self.groups()
        calls=[]
        def google(source):
            calls.append(('google',source))
            return 'ああ、そうか。'
        def sub(model,messages,timeout=120):
            self.assertEqual(model,t.SUB_MODEL)
            self.assertIn('[CURRENT_SOURCE]',messages[1]['content'])
            self.assertNotIn('以前の字幕だ。',str(messages))
            calls.append(('tuned',messages))
            return 'そういうことか。'
        old_size=(self.root/'jobs.sqlite3').stat().st_size
        out,stat,stop=t.run_arms(self.base,self.root,anchors,holdout,google,sub)
        self.assertIsNone(stop)
        self.assertEqual(len(out),96)
        self.assertEqual(len(calls),96)
        self.assertEqual(sum(r['arm']=='google_card' for r in out),80)
        self.assertEqual(sum(r['arm']=='tuned_native_holdout' for r in out),16)
        self.assertEqual(sum(r['dataset']=='heldout' for r in out),32)
        self.assertEqual(sum(r['dataset']=='anchor' for r in out),64)
        self.assertEqual(sum(r['valid_japanese'] for r in out),96)
        self.assertTrue(all(not r['structural_flags'] for r in out))
        self.assertEqual(out[64]['cue_id'],holdout[0][0]['cue_id'])
        self.assertEqual(out[80]['previous_native_context_ids'],[])
        self.assertEqual(out[81]['previous_native_context_ids'],[holdout[0][0]['cue_id']])
        self.assertEqual(out[88]['previous_native_context_ids'],[])
        self.assertEqual((self.root/'jobs.sqlite3').stat().st_size,old_size)
        store=service.Store(self.root)
        self.assertEqual(store.rows(t.JOB_ID)[514]['japanese'],'以前の字幕だ。')
        self.assertEqual(store.jobs()[0]['status'],'published')
        store.cn.close()
        for rec in t.metrics(out,stat):
            self.assertIn('NOT SCORED',rec['semantic_quality'])

    def test_structural_errors_not_cleaned_or_leaked_to_next_context(self):
        anchors,holdout=self.groups()
        count=[0]
        def contaminated(model,messages,timeout=120):
            count[0]+=1
            return 'ダメだ？」,' if count[0]==2 else '大丈夫。'
        out,stat,stop=t.run_arms(self.base,self.root,[],[holdout[0]],
                                  google_call=lambda s:'はい。',
                                  subtitle_call=contaminated)
        self.assertEqual(len(out),16)
        tuned=[r for r in out if r['arm']=='tuned_native_holdout']
        self.assertTrue(tuned[1]['structural_flags'])
        self.assertEqual(tuned[2]['previous_native_context_ids'],[tuned[0]['cue_id']])

if __name__=='__main__':
    unittest.main()
