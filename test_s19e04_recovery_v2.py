"""Deterministic finite S19E04 recovery preserving accepted v1 checkpoints."""
import contextlib
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest
from io import StringIO

import service
from tools import repair_s19e04 as repair
from tools import s19e04_recovery_v2 as rec


def episode_rows(n=151):
    def clock(s):return '%02d:%02d:%02d,000'%(s//3600,(s//60)%60,s%60)
    return [(i+1,f'{clock(i*3)} --> {clock(i*3+2)}',
             i*3000,i*3000+2000,f'ONLY_CURRENT_EN_{i+1}')
            for i in range(n)]


class RecoveryV2Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp=Path(tmp.name)
        self.video=self.tmp/'American.Dad.S19E04.mkv'
        self.video.write_bytes(b'fictional video')
        self.state=self.tmp/'private-state'
        self.rows=episode_rows()
        self.old={str(row[0]):'自然な日本語です。' for row in self.rows}
        self.old['52']='先に長い話をしてこれから出てくる台詞が読みにくくなっているのです。'*2
        self.old['53']='それは実際には違うでしょう。'
        self.old['54']='おかしい翻訳です。'
        self.en=service.render_srt(self.rows,{str(r[0]):r[4] for r in self.rows})
        self.jp=service.render_srt(self.rows,self.old)
        self.pilot=repair.intake.pilot_path(self.video)
        self.pilot.write_bytes(self.jp)
        self.calls=[]

    def source(self,video,roots):
        self.assertEqual(video,self.video)
        return self.rows,self.old.copy(),self.en,self.jp

    def repair_run(self,ask,publish=True):
        with patch.object(repair.core,'locks',return_value=contextlib.nullcontext()):
            return repair.execute(
                state=self.state,roots=(self.tmp,),ask=ask,
                selector=lambda roots:self.video,pair_loader=self.source,
                publish=publish,max_minutes=5,log=lambda *args:None)

    def test_lossless_line_break_reflow_no_model_calls(self):
        text='今日は本当に長すぎる説明になってしまったよね。'
        self.assertLessEqual(rec.q.visible_chars(text),32)
        self.assertGreater(rec.q.visible_chars(text),18)
        result=rec.reflow_unaltered_japanese(
            text,'Some context.',0,3000,[],repair.acceptable)
        self.assertIsNotNone(result)
        self.assertEqual(result.replace('\n',''),text)
        self.assertEqual(result.count('\n'),1)
        self.assertTrue(all(rec.q.visible_chars(x)<=18
                            for x in result.splitlines()))

    def test_very_fast_or_too_long_cue_not_reflowed_and_not_truncated(self):
        text='うまく読めないほど長すぎる説明をどうにかしなければならないと思っています。'
        for end in (500,4000):
            result=rec.reflow_unaltered_japanese(
                text,'This is a subtitle.',0,end,[],repair.acceptable)
            self.assertIsNone(result)
        self.assertEqual(text,'うまく読めないほど長すぎる説明をどうにかしなければならないと思っています。')

    def test_contextsafe_prompts_only_current_cue_and_advisory_budget(self):
        index=51
        for attempt in rec.ATTEMPTS:
            prompt=rec.messages(self.rows,index,attempt)
            blob=str(prompt)
            self.assertIn('ONLY_CURRENT_EN_52',blob)
            self.assertNotIn('ONLY_CURRENT_EN_51',blob)
            self.assertNotIn('ONLY_CURRENT_EN_53',blob)
            self.assertIn('at most',blob)
            self.assertIn('joke',blob)
            self.assertEqual(rec.prompt_sha(prompt),rec.prompt_sha(prompt))
        self.assertLessEqual(rec.budget(0,5000),32)
        self.assertGreaterEqual(rec.budget(0,300),10)

    def test_real_first_pass_then_distinct_v2_rejections_only_once(self):
        bad='大変長い日本語がここに入っている。'*12
        first_count=[0]
        def first(messages):
            first_count[0]+=1
            if 'ONLY_CURRENT_EN_54' in str(messages):
                return '自然な日本語です。'
            return bad
        self.assertEqual(self.repair_run(first),'held')
        first_saved=repair.checkpoint(self.state,54,self.manifest_sha())
        self.assertEqual(first_saved,'自然な日本語です。')
        first_calls=first_count[0]
        self.assertGreater(first_calls,0)
        self.assertFalse(repair.output(self.video).exists())
        second_count=[0]
        def second(messages):
            second_count[0]+=1
            self.assertIn('READABILITY BUDGET',str(messages))
            self.assertNotIn('ONLY_CURRENT_EN_51',str(messages)
                             if 'ONLY_CURRENT_EN_52' in str(messages) else 'none')
            return bad
        self.assertEqual(self.repair_run(second),'held')
        self.assertGreater(second_count[0],0)
        self.assertEqual(repair.checkpoint(self.state,54,self.manifest_sha()),
                         '自然な日本語です。')
        failures=list((self.state/'attempts-v2').glob('*.json'))
        self.assertGreater(len(failures),0)
        self.assertEqual(self.repair_run(lambda _:self.fail(
            'finite recovery ledger must block identical attempts')),'held')
        self.assertEqual(second_count[0],len(failures))
        self.assertEqual(self.pilot.read_bytes(),self.jp)

    def manifest_sha(self):
        import json
        data=json.loads((self.state/'manifest.json').read_text())
        return repair.intake.sha(json.dumps(data,sort_keys=True).encode())

    def test_second_pass_can_publish_with_no_v1_retranslation(self):
        bad='長すぎる文章を何度も繰り返して画面いっぱいになってしまっています。'*4
        first_calls=[]
        def first(messages):
            current=messages[-1]['content']
            first_calls.append(current)
            if 'ONLY_CURRENT_EN_52' in current:return '自然な日本語です。'
            return bad
        self.assertEqual(self.repair_run(first),'held')
        old_saved=repair.checkpoint(self.state,52,self.manifest_sha())
        self.assertIsNotNone(old_saved)
        calls=[]
        def second(messages):
            current=messages[-1]['content']
            calls.append(current)
            self.assertIn('READABILITY BUDGET',str(messages))
            return '自然な日本語です。'
        self.assertEqual(self.repair_run(second),'published')
        self.assertEqual(repair.checkpoint(self.state,52,self.manifest_sha()),
                         old_saved)
        self.assertFalse(any('ONLY_CURRENT_EN_52' in call for call in calls))
        self.assertNotEqual(self.pilot.read_bytes(),
                            repair.output(self.video).read_bytes())
        self.assertEqual(len(service.parse_srt(
            repair.output(self.video).read_bytes())),151)

    def test_retry_ledger_rejects_changed_input_or_corrupt_entries(self):
        prompt=rec.messages(self.rows,51,3)
        self.state.mkdir()
        rec.record_rejection(self.state,52,3,'original-sha',prompt,
                             repair.save_json)
        self.assertTrue(rec.was_rejected(
            self.state,52,3,'original-sha',prompt))
        changed=rec.messages(self.rows,52,3)
        with self.assertRaisesRegex(RuntimeError,'identity changed'):
            rec.was_rejected(self.state,52,3,'original-sha',changed)

    def test_qa_hold_is_not_systemd_notimplemented_error(self):
        with patch.object(repair,'execute',return_value='held'):
            import sys
            from unittest.mock import patch as mocked
            with mocked('sys.stdout',new_callable=StringIO) as out:
                code=repair.cli(['run'])
            self.assertEqual(code,0)
            self.assertIn('S19E04_REPAIR_RESULT held published False',
                          out.getvalue())


if __name__=='__main__':
    unittest.main()
