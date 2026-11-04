"""Research-only LEGACY JSON style-profile tests; not production subtitle E4B."""
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import localization_policy as lp
import service as s

EN_SOURCE=(b'1\n00:00:01,000 --> 00:00:02,200\n'
           b'That was a fucking disaster.\n\n'
           b'2\n00:00:02,250 --> 00:00:04,250\n'
           b'Don\'t you dare leave me here.\n')


class LocalizationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        db=s.Store(root)
        db.add('fixture',root/'fictional.mkv',EN_SOURCE,'eng')
        self.rows=db.rows('fixture')
        db.cn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def stub(self,received):
        core=types.ModuleType('bruiser_auto')
        core.parse_srt=lambda path: [
            types.SimpleNamespace(id=x[0],text=x[4])
            for x in s.parse_srt(Path(path).read_bytes())]
        core.build_prompt=lambda cues,start,end,memory:('BASE SYSTEM INSTRUCTIONS','structured payload')
        def call(url,model,system,payload,ids,timeout):
            received.append({'system':system,'payload':payload,'ids':ids})
            return {1:'ひどい失敗だった。',2:'置いていくんじゃねえ。'}
        core.call_ollama=call
        core.preserve_tags=lambda english,japanese:japanese
        return core

    def test_profile_preserves_structure_and_explicit_intent(self):
        received=[]
        with patch.dict(sys.modules,{'bruiser_auto':self.stub(received)}):
            result=s.legacy_json_translation_call(Path(self.tmp.name),self.rows,'',style='natural_8')
        self.assertEqual(result,{'1':'ひどい失敗だった。','2':'置いていくんじゃねえ。'})
        system=received[0]['system']
        self.assertTrue(system.startswith('BASE SYSTEM INSTRUCTIONS'))
        self.assertIn('DO NOT CENSOR OR SANITIZE',system)
        self.assertIn('idioms, sarcasm',system)
        self.assertIn('soft ~11 Japanese chars',system)  # 1.2s
        self.assertIn('soft ~18 Japanese chars',system)  # 2s
        self.assertIn('Keep the exact cue IDs',system)
        self.assertEqual(received[0]['payload'],'structured payload')
        self.assertEqual(received[0]['ids'],[1,2])

    def test_baseline_remains_byte_for_byte_original(self):
        received=[]
        with patch.dict(sys.modules,{'bruiser_auto':self.stub(received)}):
            with patch.dict(os.environ,{'SUBHUB_LOCALIZATION_STYLE':'baseline'}):
                s.legacy_json_translation_call(Path(self.tmp.name),self.rows,'')
        self.assertEqual(received[0]['system'],'BASE SYSTEM INSTRUCTIONS')
        self.assertEqual(received[0]['payload'],'structured payload')

    def test_profile_environment_opt_in_and_bad_setting_fail_closed(self):
        received=[]
        with patch.dict(sys.modules,{'bruiser_auto':self.stub(received)}):
            with patch.dict(os.environ,{'SUBHUB_LOCALIZATION_STYLE':'natural_8'}):
                s.legacy_json_translation_call(Path(self.tmp.name),self.rows,'')
            with patch.dict(os.environ,{'SUBHUB_LOCALIZATION_STYLE':'unknown'}):
                with self.assertRaisesRegex(ValueError,'Unknown localization style'):
                    s.legacy_json_translation_call(Path(self.tmp.name),self.rows,'')
        self.assertEqual(len(received),1)

    def test_faithful_8_has_no_soft_character_quota_and_preserves_adult_intent(self):
        received=[]
        with patch.dict(sys.modules,{'bruiser_auto':self.stub(received)}):
            s.legacy_json_translation_call(Path(self.tmp.name),self.rows,'',style='faithful_8')
        system=received[0]['system']
        self.assertIn('MEANING-FIRST ADULT JAPANESE SUBTITLES',system)
        self.assertIn('directed AT someone',system)
        self.assertIn('Sexual teasing must remain explicitly',system)
        self.assertIn('rhetorical accusation',system)
        self.assertIn('Keep each speaker turn',system)
        self.assertNotIn('soft ~11 Japanese chars',system)
        self.assertIn('local cue 1: 1.2s on screen',system)
        self.assertEqual(received[0]['payload'],'structured payload')

    def test_explicit_faithful_8_does_not_change_default_prompt(self):
        received=[]
        with patch.dict(sys.modules,{'bruiser_auto':self.stub(received)}):
            with patch.dict(os.environ,{'SUBHUB_LOCALIZATION_STYLE':'baseline'}):
                s.legacy_json_translation_call(Path(self.tmp.name),self.rows,'',style='faithful_8')
                s.legacy_json_translation_call(Path(self.tmp.name),self.rows,'')
        self.assertIn('MEANING-FIRST',received[0]['system'])
        self.assertEqual(received[1]['system'],'BASE SYSTEM INSTRUCTIONS')
    def test_no_hard_truncation_and_no_db_mutation(self):
        note=lp.enhance_system('schema',self.rows)
        self.assertIn('SOFT guidance, not limits',note)
        self.assertIn('do NOT sacrifice meaning',note)
        db=s.Store(Path(self.tmp.name))
        self.assertEqual([r['japanese'] for r in db.rows('fixture')],[None,None])
        db.cn.close()


if __name__=='__main__':
    unittest.main()
