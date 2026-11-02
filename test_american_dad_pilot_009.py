"""Offline 009 canary tests: extraction safety, frozen sources, resume and SRT publishing."""
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

from tools import american_dad_intake_009 as intake
from tools import american_dad_core_009 as core
from tools import american_dad_pilot_009 as pilot


def english_srt(n=151):
    lines=[]
    for i in range(n):
        a=i*2
        b=a+1
        def stamp(t):return f'00:{t//60:02}:{t%60:02},000'
        lines.append(f'{i+1}\n{stamp(a)} --> {stamp(b)}\nStan and Roger talk about cue {i}.')
    return ('\n\n'.join(lines)+'\n').encode('utf8')


class AmericanDad009Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.base=Path(self.t.name)
        self.root=self.base/'media'
        self.season=self.root/'American Dad'/'Season 01'
        self.season.mkdir(parents=True)
        self.video=self.season/'American.Dad.S01E01.mkv'
        self.video.write_bytes(b'fake video for no-network offline test')
        self.english=self.video.with_name(self.video.stem+'.en.srt')
        self.english.write_bytes(english_srt())
        self.output=self.base/'scratch'
        self.profile=self.base/'series.json'
        self.profile.write_text('{"series":"American Dad"}',encoding='utf8')
        self.track={'kind':'sidecar','path':str(self.english)}

    def tearDown(self):
        self.t.cleanup()

    def test_discovery_and_sidecar_precedence(self):
        self.assertEqual(list(intake.discover((self.root,))),[self.video])
        self.assertFalse(intake.existing_ja(self.video))
        raw,rows=intake.extract(self.video,self.track)
        self.assertEqual(raw,self.english.read_bytes())
        self.assertEqual(len(rows),151)
        self.assertTrue(intake.safe_video(self.video,(self.root,)))
        self.assertFalse(intake.safe_video(self.video,(self.base/'other',)))

    def test_ffprobe_english_primary_and_embedded_ja_block(self):
        def runner(payload):
            return lambda *a,**kw:SimpleNamespace(stdout=json.dumps(
                {'streams':payload}).encode())
        en_audio={'codec_type':'audio','tags':{'language':'eng'},
                  'disposition':{'default':1}}
        en_sub={'codec_type':'subtitle','index':3,'codec_name':'subrip',
                'tags':{'language':'eng'},'disposition':{'default':1}}
        self.assertEqual(intake.tracks(self.video,runner([en_audio,en_sub])),
                         {'kind':'embedded','index':3})
        ja_sub={'codec_type':'subtitle','index':4,'codec_name':'ass',
                'tags':{'language':'jpn'}}
        with self.assertRaisesRegex(ValueError,'embedded Japanese'):
            intake.tracks(self.video,runner([en_audio,en_sub,ja_sub]))
        with self.assertRaisesRegex(ValueError,'Unverified English'):
            intake.tracks(self.video,runner([{'codec_type':'audio',
                                             'tags':{'language':'jpn'}}]))

    def test_existing_ja_blocks_catalog_and_preserves_approved_bytes(self):
        human=self.video.with_name(self.video.stem+'.Editorial.ja.srt')
        human.write_bytes(b'approved subtitle unchanged')
        before=human.read_bytes()
        self.assertTrue(intake.existing_ja(self.video))
        with patch.object(intake,'tracks',return_value=self.track):
            result,skips=intake.catalog((self.root,),5)
        self.assertEqual(result,[])
        self.assertGreater(skips.get('already_japanese',0),0)
        self.assertEqual(human.read_bytes(),before)

    def test_freeze_never_modifies_video_and_manifest_is_resume_stable(self):
        before=self.video.read_bytes()
        with patch.object(intake,'tracks',return_value=self.track):
            result=pilot.freeze(5,(self.root,),self.output,self.profile)
        self.assertEqual(len(result['episodes']),1)
        self.assertEqual(result['model_id'],core.MODEL_ID)
        self.assertEqual(self.video.read_bytes(),before)
        with patch.object(intake,'catalog',side_effect=AssertionError('Resampled')):
            repeat=pilot.freeze(5,(self.root,),self.output,self.profile)
        self.assertEqual(result,repeat)
        with self.assertRaisesRegex(RuntimeError,'manifest identity'):
            pilot.freeze(4,(self.root,),self.output,self.profile)

    def test_native_lookahead_and_advisory_bible_in_prompt(self):
        _,rows=intake.extract(self.video,self.track)
        msg=core.prompt(rows,5,['日本語は文脈です'],'Stan is Roger friend',
                        'series note','episode note')
        self.assertEqual(len(msg),2)
        self.assertIn('CURRENT_ENGLISH',msg[1]['content'])
        self.assertIn('NEXT_ENGLISH',msg[1]['content'])
        self.assertIn('PREVIOUS_JAPANESE',msg[1]['content'])
        self.assertIn('Advisory'.upper(),msg[0]['content'].upper())
        self.assertTrue(core.valid('わかったよ。',rows[5][4]))
        self.assertFalse(core.valid('{"answer":"hi"}',rows[5][4]))

    def test_full_episode_writes_distinct_pilot_and_resume_no_retranslation(self):
        with patch.object(intake,'tracks',return_value=self.track):
            manifest=pilot.freeze(5,(self.root,),self.output,self.profile)
            entry=manifest['episodes'][0]
            seen=[]
            def fake(messages):
                seen.append(messages)
                return 'わかった。'
            with patch.object(core,'note',return_value=None):
                outcome=pilot.translate(entry,'{}',None,self.output,(self.root,),
                                        fake,True)
                self.assertEqual(outcome['state'],'published_new_pilot')
                self.assertEqual(len(seen),151)
                path=intake.pilot_path(self.video)
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_bytes().count(b'-->'),151)
                before=path.read_bytes()
                same=pilot.translate(entry,'{}',None,self.output,(self.root,),
                                     lambda _:self.fail('Reran model'),True)
                self.assertEqual(same['state'],'already_published_identical')
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(self.english.read_bytes(),english_srt())
                self.assertEqual(len(list((self.output/'episodes'/entry['episode']/'cues').glob('*.json'))),151)

    def test_failed_translation_does_not_publish_and_is_bounded(self):
        with patch.object(intake,'tracks',return_value=self.track):
            info=pilot.freeze(5,(self.root,),self.output,self.profile)['episodes'][0]
            with patch.object(core,'note',return_value=None):
                result=pilot.translate(info,'{}',None,self.output,(self.root,),
                                       lambda _: 'not Japanese',True)
            self.assertEqual(result['state'],'incomplete')
            self.assertFalse(intake.pilot_path(self.video).exists())
            errors=list((self.output/'episodes'/info['episode']/'errors').glob('*.json'))
            self.assertEqual(len(errors),24)

    def test_embedded_english_subtitle_extraction_uses_exact_stream(self):
        mapped=[]
        def fake_runner(cmd,**kwargs):
            mapped.append(cmd)
            return SimpleNamespace(stdout=english_srt(154))
        raw,rows=intake.extract(self.video,{'kind':'embedded','index':3},
                                runner=fake_runner)
        self.assertEqual(len(rows),154)
        self.assertIn('0:3',mapped[0])
        self.assertEqual(raw,english_srt(154))

    def test_new_human_ja_sidecar_between_plan_and_inference_blocks(self):
        with patch.object(intake,'tracks',return_value=self.track):
            entry=pilot.freeze(5,(self.root,),self.output,self.profile)['episodes'][0]
            human=self.video.with_name(self.video.stem+'.ja.srt')
            human.write_bytes(b'Human-localized Japanese subtitle')
            before=human.read_bytes()
            with patch.object(core,'note',return_value=None):
                with self.assertRaisesRegex(RuntimeError,'Already has Japanese'):
                    pilot.translate(entry,'{}',None,self.output,(self.root,),
                                    lambda _:self.fail('Unexpected model call'),True)
        self.assertEqual(human.read_bytes(),before)
        self.assertFalse(intake.pilot_path(self.video).exists())

    def test_one_command_shell_has_valid_bash_syntax(self):
        import subprocess
        script=Path(__file__).resolve().parent/'tools/run_american_dad_pilot_009.sh'
        result=subprocess.run(['bash','-n',str(script)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        body=script.read_text(encoding='utf8')
        self.assertIn('--episodes 5',body)
        self.assertIn('--publish',body)
        self.assertNotIn('systemctl restart',body)

    def test_exclusive_worker_lock_contends(self):
        import fcntl
        holder=self.base/'subhub1-state'/'run.lock'
        holder.parent.mkdir()
        with holder.open('a+b') as stream:
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError,'Another subtitle worker'):
                with core.locks(self.base):
                    pass

if __name__=='__main__':
    unittest.main()
