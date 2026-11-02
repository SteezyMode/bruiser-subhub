"""Synthetic, no-GPU regressions for original-checkpoint-preserving v011r1."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import american_dad_core_009 as core
from tools import american_dad_intake_009 as intake
from tools import american_dad_utterance_011 as original
from tools import semantic_groups_011 as semantic
from tools import rescue_utterance_011 as rescue


def english_srt(n=151):
    def clock(s):
        return '%02d:%02d:%02d,000'%(s//3600,(s//60)%60,s%60)
    rows=[]
    for i in range(n):
        english=('This sentence will continue'
                 if i%3==0 else
                 'to the next source caption.'
                 if i%3==1 else 'A different complete utterance.')
        rows.append('%d\n%s --> %s\n%s'%(i+1,clock(i*2),
                                         clock(i*2+1),english))
    return ('\n\n'.join(rows)+'\n').encode('utf8')


class FrozenRescue(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.media=self.root/'media'
        season=self.media/'American Dad'/'Season 19'
        season.mkdir(parents=True)
        self.video=season/'American Dad S19E10.mkv'
        self.video.write_bytes(b'synthetic media')
        self.source=season/'American Dad S19E10.en.srt'
        self.source.write_bytes(english_srt())
        self.track={'kind':'sidecar','path':str(self.source)}
        self.original_state=self.root/'original-v011'
        self.rescue_state=self.root/'separate-recovery'
        self.profile=self.root/'profile.json'
        self.profile.write_text('{"recurring_people":[]}',encoding='utf8')
        self.locks=self.root/'locks'
        with patch.object(intake,'tracks',return_value=self.track):
            self.entry=original.freeze(3,(self.media,),
                    self.original_state,self.profile)['episodes'][0]
        self.rows=service.parse_srt(english_srt())
        self.groups=semantic.plan(self.rows)
        self.assertGreater(len(self.groups),5)
        self.good=self.groups[0]
        self.failed=next(g for g in self.groups[1:] if len(g)>1)
        self.save_original_good(self.good)
        self.create_original_errors(self.failed)
        self.calls=[]
        self.base_paths={
            str(p):p.read_bytes() for p in self.original_state.rglob('*')
            if p.is_file()
        }

    def good_ja(self):
        return '自然な日本語です。'

    def save_original_good(self,unit):
        path=original.unit_file(
            self.original_state/'episodes'/self.entry['episode'],unit)
        core.save(path,{
            'schema':original.SCHEMA,
            'source_sha':self.entry['source_sha'],
            'model_id':core.MODEL_ID,
            'pipeline_sha':original.pipeline_sha(),
            'unit_sha':semantic.unit_sha(unit),
            'ids':[r[0] for r in unit],
            'translations':{str(r[0]):self.good_ja() for r in unit},
            'attempt':1,
        })

    def create_original_errors(self,unit):
        folder=self.original_state/'episodes'/self.entry['episode']/'attempts'
        for n in (1,2,3):
            core.save(folder/('%05d-%05d-%d.json'%(
                unit[0][0],unit[-1][0],n)),{
                'ids':[r[0] for r in unit],
                'error':'RuntimeError: Output length cap',
            })

    def model(self,msg,json_mode=False):
        self.calls.append((msg,json_mode))
        if json_mode:
            text=msg[-1]['content']
            payload=text.split('[ALL_TARGET_CUES]\n',1)[1].split(
                '\n[/ALL_TARGET_CUES]',1)[0]
            targets=json.loads(payload)
            return json.dumps({x['id']:self.good_ja() for x in targets},
                              ensure_ascii=False)
        return self.good_ja()

    def execute(self,ask=None,publish=True):
        with patch.object(intake,'tracks',return_value=self.track):
            return rescue.run(
                minutes=4,publish=publish,state=self.rescue_state,
                original_state=self.original_state,roots=(self.media,),
                profile=self.profile,ask=ask or self.model,base=self.locks)

    def test_uses_all_original_saved_units_and_fallback_failed_group(self):
        result=self.execute()[0]
        self.assertEqual(result['state'],'published_new_recovery')
        self.assertEqual(result['accepted_cues'],151)
        self.assertEqual(result['units']['original_units'],1)
        self.assertGreater(result['units']['fallback_units'],0)
        self.assertGreater(result['units']['new_group_units'],0)
        self.assertTrue(rescue.sidecar(self.video).is_file())
        self.assertEqual(rescue.sidecar(self.video).read_bytes().count(b'-->'),151)
        self.assertEqual(self.base_paths,{
            str(p):p.read_bytes() for p in self.original_state.rglob('*')
            if p.is_file()})
        # Known failed group must NOT cause one more grouped JSON request.
        old_ids={str(r[0]) for r in self.failed}
        for msg,json_mode in self.calls:
            if json_mode:
                ids={x['id'] for x in json.loads(
                    msg[-1]['content'].split('[ALL_TARGET_CUES]\n',1)[1]
                    .split('\n[/ALL_TARGET_CUES]',1)[0])}
                self.assertFalse(old_ids & ids)
        pre=len(self.calls)
        resume=self.execute()[0]
        self.assertEqual(resume['state'],'already_published_identical')
        self.assertEqual(pre,len(self.calls))

    def test_fallback_current_cue_prompts_never_contain_future_cue(self):
        before,identity=rescue.frozen(self.original_state,self.rescue_state,
                                      self.profile)
        partial={str(r[0]):self.good_ja() for r in self.good}
        prompt_sources=[]
        def ask(msg,json_mode=False):
            prompt_sources.append((msg,json_mode))
            return self.model(msg,json_mode=json_mode)
        out,mode=rescue.translate_unit(self.failed,self.rows,partial,'{}',
                  self.entry,self.rescue_state,identity,ask,self.original_state)
        self.assertEqual(mode,'isolated_singletons')
        self.assertEqual(len(out),len(self.failed))
        self.assertTrue(all(not structured for _,structured in prompt_sources))
        for index,(messages,_) in enumerate(prompt_sources):
            self.assertIn(self.failed[index][4],
                          messages[-1]['content'])
            # A singleton sees NO raw following source English in its prompt.
            if index+1<len(self.failed):
                next_source=self.failed[index+1][4]
                # If the specific current line repeats verbatim, no useful
                # assertion can distinguish current from future in the prompt.
                if next_source!=self.failed[index][4]:
                    self.assertNotIn('[ALL_TARGET_CUES]',
                                     messages[-1]['content'])

    def test_failed_recovery_cue_keeps_progress_and_never_publishes_partial(self):
        held_id=self.failed[-1][0]
        prompt_count=[]
        def sometimes_invalid(messages,json_mode=False):
            if not json_mode and '[CURRENT_ENGLISH]' in messages[-1]['content']:
                # Distinguish just the single source: this case chooses
                # a real bounded failure, not synthetic early process abort.
                if messages[-1]['content'].split('[CURRENT_ENGLISH]\n',1)[1].split(
                    '\n[/CURRENT_ENGLISH]',1)[0] == self.failed[-1][4]:
                    prompt_count.append(held_id)
                    return 'Not Japanese'
            return self.model(messages,json_mode)
        with patch.object(intake,'tracks',return_value=self.track):
            first=rescue.run(4,True,self.rescue_state,self.original_state,
                             (self.media,),self.profile,sometimes_invalid,
                             self.locks)[0]
        self.assertEqual(first['state'],'incomplete')
        self.assertFalse(rescue.sidecar(self.video).exists())
        self.assertTrue((self.rescue_state/'episodes'/self.entry['episode']/
                         'cues'/('%05d.json'%self.failed[0][0])).is_file())
        pre=len(prompt_count)
        with patch.object(intake,'tracks',return_value=self.track):
            again=rescue.run(4,True,self.rescue_state,self.original_state,
                             (self.media,),self.profile,sometimes_invalid,
                             self.locks)[0]
        self.assertEqual(again['state'],'incomplete')
        self.assertEqual(pre,len(prompt_count))
        self.assertEqual(self.base_paths,{
            str(p):p.read_bytes() for p in self.original_state.rglob('*')
            if p.is_file()})

    def test_tampered_original_code_manifest_and_checkpoint_fail_closed(self):
        with patch.object(original,'pipeline_sha',return_value='unexpected'):
            with self.assertRaisesRegex(RuntimeError,'installed code'):
                rescue.frozen(self.original_state,self.rescue_state,self.profile)
        before,identity=rescue.frozen(self.original_state,self.rescue_state,
                                     self.profile)
        self.assertEqual(before['schema'],original.SCHEMA)
        saved=self.original_state/'episodes'/self.entry['episode']/'units'/(
            '%05d-%05d.json'%(self.good[0][0],self.good[-1][0]))
        doc=json.loads(saved.read_text())
        doc['unit_sha']='bad'
        saved.write_text(json.dumps(doc))
        with patch.object(intake,'tracks',return_value=self.track):
            result=rescue.run(4,True,self.rescue_state,self.original_state,
                              (self.media,),self.profile,self.model,
                              self.locks)[0]
        self.assertEqual(result['state'],'held')
        self.assertFalse(rescue.sidecar(self.video).exists())

    def test_preexisting_japanese_sidecar_is_never_modified(self):
        old=self.video.with_name(self.video.stem+'.Bruiser ContextSafe v2 Japanese.ja.srt')
        old.write_bytes(b'owner JA track')
        result=self.execute()[0]
        self.assertEqual(result['state'],'held')
        self.assertEqual(old.read_bytes(),b'owner JA track')
        self.assertFalse(rescue.sidecar(self.video).exists())

    def test_recovery_draft_target_collision_and_code_identity(self):
        old,identity=rescue.frozen(self.original_state,self.rescue_state,
                                   self.profile)
        with patch.object(rescue,'version_sha',return_value='changed-code'):
            with self.assertRaisesRegex(RuntimeError,'identity/code/source'):
                rescue.frozen(self.original_state,self.rescue_state,self.profile)
        target=rescue.sidecar(self.video)
        target.write_bytes(b'an existing subtitle')
        result=self.execute()[0]
        self.assertEqual(result['state'],'held')
        self.assertEqual(target.read_bytes(),b'an existing subtitle')

    def test_wrapper_never_stages_original_frozen_modules(self):
        script=Path(__file__).resolve().parent/'tools/run_utterance_rescue_011.sh'
        process=subprocess.run(['bash','-n',str(script)],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        text=script.read_text()
        self.assertIn('tools/rescue_utterance_011.py',text)
        self.assertNotIn('scp -q service.py',text)
        self.assertNotIn('systemctl restart',text)
        self.assertNotIn('docker restart',text)


if __name__=='__main__':
    unittest.main()
