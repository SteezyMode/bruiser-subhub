"""Synthetic, fully offline tests of v013 focused-per-cue context pilot."""
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import unittest
from unittest.mock import patch

from tools import american_dad_core_009 as core
from tools import utterance_formatlab_012 as prior
from tools import utterance_focuslab_013 as focus
from test_utterance_formatlab_012 import Lab012


class FocusLab013(unittest.TestCase):
    def setUp(self):
        self.fixture=Lab012('test_malformed_numbered_lines_and_cue_mapping_are_blocked')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.new_state=self.fixture.root/'new-focus-013'
        self.original_before=dict(self.fixture.before)
        self.calls=[]
        identity,rows=self.fixture.sample()
        for i,item in enumerate(identity['selected']):
            group=prior.group_for(item,rows[item['episode']])
            if i<9:
                def one_sentence(msg,mode):
                    self.assertEqual(mode,'lines')
                    return {'content':'これは二つの字幕全体をまとめた日本語です。',
                            'done_reason':'stop','eval_count':25,
                            'prompt_eval_count':100,'total_duration_ns':1000}
                result=prior.run_one(self.fixture.state,item,group,
                                     'lines','{}',one_sentence)
                self.assertEqual(result['status'],'failed')
            else:
                result=prior.run_one(self.fixture.state,item,group,
                                     'lines','{}',self.fixture.fake)
                self.assertEqual(result['status'],'valid')

    def prepare(self):
        return focus.ensure_original(
            state=self.new_state,source_state=self.fixture.original_state,
            old_lab=self.fixture.state,profile=self.fixture.profile,
            recovered_state=self.fixture.recovery_state)

    def fake_ask(self,messages,json_mode=False):
        self.assertFalse(json_mode)
        self.calls.append(messages)
        cue=re.search(r'TARGET_ID = (\d+)',messages[-1]['content'])
        self.assertIsNotNone(cue)
        self.assertIn('[WHOLE_JAPANESE_CONTEXT_NOT_OUTPUT]',
                      messages[-1]['content'])
        self.assertIn('TARGET_EN = ',messages[-1]['content'])
        self.assertIn('CONTEXT_ONLY_EN = ',messages[-1]['content'])
        return '日本語%dです。'%int(cue[1])

    def run(self,ask=None):
        return focus.run(1,self.new_state,self.fixture.original_state,
                         self.fixture.state,self.fixture.profile,
                         self.fixture.recovery_state,ask or self.fake_ask,
                         self.fixture.lock_root)

    def test_real_selection_logic_is_nine_coherent_unnumbered_pairs(self):
        identity,english,baseline=self.prepare()
        self.assertEqual(len(identity['selected']),9)
        self.assertEqual(sum(len(x['cue_ids']) for x in identity['selected']),18)
        for item in identity['selected']:
            group=focus.group_for(item,english)
            self.assertEqual(len(group),2)
            self.assertIn('二つの字幕',item['whole_japanese'])
            self.assertEqual(len(item['cue_ids']),2)
            self.assertTrue(all(str(x[0]) in baseline[item['episode']]
                                for x in group))
        saved=(self.new_state/'selection.json').read_bytes()
        self.prepare()
        self.assertEqual((self.new_state/'selection.json').read_bytes(),saved)
        self.assertEqual(self.original_before,{
            str(p):p.read_bytes() for p in self.fixture.original_state.rglob('*')
            if p.is_file()})

    def test_18_single_cue_calls_only_save_new_private_checkpoints(self):
        result=self.run()
        self.assertEqual(result['expected_calls'],18)
        self.assertEqual(result['completed_calls'],18)
        self.assertEqual(result['valid_cues'],18)
        self.assertEqual(result['failed_cues'],0)
        self.assertEqual(result['complete_utterances'],9)
        self.assertEqual(len(self.calls),18)
        self.assertEqual(list(self.new_state.rglob('*.srt')),[])
        self.assertEqual(self.original_before,{
            str(p):p.read_bytes() for p in self.fixture.original_state.rglob('*')
            if p.is_file()})
        once=len(self.calls)
        self.assertEqual(self.run(),result)
        self.assertEqual(len(self.calls),once)

    def test_bounded_failed_cue_attempt_is_not_retried_on_resume(self):
        identity,english,_=self.prepare()
        item=identity['selected'][0]
        group=focus.group_for(item,english)
        def fail(messages,json_mode=False):
            self.calls.append(messages)
            return 'This is an English-only non-translation.'
        d=focus.one(self.new_state,item,group,group[0],'{}',fail)
        self.assertEqual(d['status'],'failed')
        self.assertEqual(d['failure_category'],'invalid_ja_or_speaker')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(focus.one(self.new_state,item,group,group[0],
                                   '{}',fail),d)
        self.assertEqual(len(self.calls),1)
        self.assertFalse(list(self.new_state.rglob('*.srt')))

    def test_focus_prompt_current_cue_only_and_separate_context(self):
        identity,english,_=self.prepare()
        item=identity['selected'][0]
        g=focus.group_for(item,english)
        one=focus.focus_messages(g,g[0],item['whole_japanese'],'{}')
        two=focus.focus_messages(g,g[1],item['whole_japanese'],'{}')
        self.assertIn('TARGET_ID = '+str(g[0][0]),one[-1]['content'])
        self.assertIn('TARGET_ID = '+str(g[1][0]),two[-1]['content'])
        self.assertIn('CONTEXT_NOT_TARGET',one[-1]['content'])
        self.assertIn('CONTEXT_NOT_TARGET',two[-1]['content'])
        self.assertIn('CONTEXT_ONLY_EN',one[-1]['content'])
        self.assertIn('WHOLE_JAPANESE_CONTEXT_NOT_OUTPUT',one[-1]['content'])
        self.assertNotEqual(one[-1]['content'],two[-1]['content'])

    def test_private_archive_keeps_ja_english_only_in_private_output(self):
        self.run()
        buffer=io.BytesIO()
        stats=focus.export(self.new_state,self.fixture.original_state,
                           self.fixture.state,self.fixture.profile,
                           self.fixture.recovery_state,buffer)
        self.assertEqual(stats['completed_calls'],18)
        with tarfile.open(fileobj=io.BytesIO(buffer.getvalue()),mode='r:gz') as arc:
            self.assertEqual(arc.getnames(),[
                'PRIVATE_focuslab_013_bilingual_comparison.json'])
            data=json.load(arc.extractfile(arc.getnames()[0]))
        self.assertEqual(len(data['cases']),9)
        self.assertEqual(data['summary']['valid_cues'],18)
        for case in data['cases']:
            self.assertEqual(len(case['cues']),2)
            self.assertEqual(len(case['focused_outputs']),2)
            self.assertTrue(all('published_baseline_japanese' in x
                                for x in case['cues']))
            self.assertIn('二つの字幕',case['original_unnumbered_whole_ja'])
        self.assertNotIn(str(self.fixture.original_state),str(data))
        self.assertFalse(list(self.new_state.rglob('*.srt')))

    def test_incomplete_export_and_source_modification_fail_closed(self):
        self.prepare()
        with self.assertRaisesRegex(RuntimeError,'incomplete'):
            focus.export(self.new_state,self.fixture.original_state,
                         self.fixture.state,self.fixture.profile,
                         self.fixture.recovery_state,io.BytesIO())
        with patch.object(focus,'code_sha',return_value='new-code-sha'):
            with self.assertRaisesRegex(RuntimeError,'identity changed'):
                self.prepare()
        source=Path(self.fixture.entries['S19E10']['source_path'])
        source.write_bytes(source.read_bytes().replace(
            b'the new plan',b'the old plan'))
        with self.assertRaisesRegex(RuntimeError,'source hash mismatch'):
            self.prepare()

    def test_mac_scripts_stage_only_new_code_and_export_readonly(self):
        folder=Path(__file__).resolve().parent/'tools'
        for name in ('run_utterance_focuslab_013.sh',
                     'collect_utterance_focuslab_013.sh'):
            path=folder/name
            process=subprocess.run(['bash','-n',str(path)],
                                   capture_output=True,text=True)
            self.assertEqual(process.returncode,0,process.stderr)
            data=path.read_text()
            self.assertNotIn('docker restart',data)
            self.assertNotIn('systemctl',data)
            self.assertNotIn('scp -q service.py',data)
        self.assertNotIn('scp ',(folder/'collect_utterance_focuslab_013.sh').read_text())
        self.assertIn('tools/utterance_focuslab_013.py',
                      (folder/'run_utterance_focuslab_013.sh').read_text())


if __name__=='__main__':
    unittest.main()
