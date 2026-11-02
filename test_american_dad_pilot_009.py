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
            self.assertEqual(len(errors),72)

    def test_recover_only_missing_cue_reuses_150_accepted_cues(self):
        # Mirrors owner: two failed attempts were recorded during initial run,
        # but 150 completed lines MUST NOT be regenerated on resume.
        with patch.object(intake,'tracks',return_value=self.track):
            entry=pilot.freeze(5,(self.root,),self.output,self.profile)['episodes'][0]
            raw,rows=intake.extract(self.video,self.track)
            folder=self.output/'episodes'/entry['episode']
            for row in rows:
                if row[0]==6:
                    continue
                core.save(folder/'cues'/('%05d.json'%row[0]),{
                    'cue_id':row[0], 'source_sha':entry['source_sha'],
                    'model_id':core.MODEL_ID,'japanese':'元の訳です。',
                    'valid':True,'seconds':0.03
                })
            original=(folder/'cues'/'00005.json').read_bytes()
            for n in (1,2):
                core.save(folder/'errors'/('00006-%d.json'%n),{
                    'cue_id':6,'error':'Invalid Japanese/format','reply':'no Japanese'
                })
            previous_error=(folder/'errors'/'00006-2.json').read_bytes()
            seen=[]
            def rescue(messages):
                seen.append(messages)
                return '回復した訳です。'
            with patch.object(core,'note',return_value=None):
                result=pilot.translate(entry,'{}',None,self.output,(self.root,),
                                       rescue,True)
            self.assertEqual(result['state'],'published_new_pilot')
            self.assertEqual(len(seen),1)
            self.assertIn('CURRENT:',seen[0][1]['content'])
            self.assertTrue((folder/'cues'/'00006.json').is_file())
            self.assertEqual(core.load(folder/'cues'/'00006.json')['attempt'],3)
            self.assertEqual((folder/'cues'/'00005.json').read_bytes(),original)
            self.assertEqual((folder/'errors'/'00006-2.json').read_bytes(),previous_error)
            self.assertTrue(intake.pilot_path(self.video).is_file())

    def test_source_supported_italicized_show_title_is_legitimate_japanese(self):
        source='Now go be the star of <i>Langley Dollar Listings.</i>'
        literal='じゃあ、<i>Langley Dollar Listings</i>の主役になってろ。'
        later='さあ、<i lang="en">Langley Dollar Listings</i>の主役になって。'
        self.assertEqual(core.normalized_srt_markup(literal,source),literal)
        self.assertEqual(core.normalized_srt_markup(later,source),
                         'さあ、<i>Langley Dollar Listings</i>の主役になって。')
        self.assertTrue(core.valid(literal,source))
        self.assertTrue(core.valid(later,source))
        # No unauthorized HTML or free-form attributes allowed, even with Japanese.
        for bad in ('日本語<script>alert(1)</script>',
                    '日本語<b>太字</b>',
                    '日本語<i>閉じていない',
                    '日本語</i>逆順<i>',
                    '日本語<i><i>入れ子</i></i>',
                    '日本語<i onclick="f()">危険</i>'):
            self.assertIsNone(core.normalized_srt_markup(bad,source),bad)
            self.assertFalse(core.valid(bad,source),bad)
        self.assertFalse(core.valid(literal,'No source italic tags.'))

    def test_recover_italicized_failed_cue_without_new_model_calls_or_edits(self):
        # Reproduces real episode cue 321: six immutable error records,
        # four identical softer responses in the later prompt. Only missing
        # cue can be created; 150 already accepted Japanese cues stay byte-identical.
        with patch.object(intake,'tracks',return_value=self.track):
            entry=pilot.freeze(5,(self.root,),self.output,self.profile)['episodes'][0]
            folder=self.output/'episodes'/entry['episode']
            raw,rows=intake.extract(self.video,self.track)
            cue_id=6
            source='Now go be the star of <i>Langley Dollar Listings.</i>'
            rows[5]=(rows[5][0],rows[5][1],rows[5][2],rows[5][3],source)
            # The on-disk source hash remains frozen, and this unit test
            # tests the recovery helper independently of live source changes.
            for i in range(1,7):
                reply=('じゃあ、<i>Langley Dollar Listings</i>の主役になってろ。'
                       if i<=2 else
                       'さあ、<i lang="en">Langley Dollar Listings</i>の主役になって。')
                core.save(folder/'errors'/('%05d-%d.json'%(cue_id,i)),{
                    'cue_id':cue_id,'error':'Invalid Japanese/format','reply':reply})
            prior=(folder/'errors'/'00006-6.json').read_bytes()
            good=folder/'cues'/'00005.json'
            core.save(good,{'cue_id':5,'japanese':'既存の字幕。','valid':True,
                            'model_id':core.MODEL_ID,'source_sha':entry['source_sha']})
            previous=good.read_bytes()
            result=pilot.recover_saved_italic_reply(folder,cue_id,source,
                                                    entry['source_sha'])
            self.assertIsNotNone(result)
            self.assertEqual(result['recovered_from_saved_attempt'],3)
            self.assertEqual(result['japanese'],
                             'さあ、<i>Langley Dollar Listings</i>の主役になって。')
            self.assertTrue(core.valid(result['japanese'],source))
            self.assertEqual(prior,(folder/'errors'/'00006-6.json').read_bytes())
            self.assertEqual(previous,good.read_bytes())
            self.assertFalse((folder/'cues'/'00006.json').exists())

    def test_six_saved_italics_failures_can_publish_without_regeneration(self):
        # End-to-end with a synthetic episode that includes source italics;
        # make all existing checkpoints read-only input and verify the one
        # missing cue is recovered, with no model callback and no changed JA.
        with patch.object(intake,'tracks',return_value=self.track):
            raw=self.english.read_bytes()
            replacement=raw.replace(b'Stan and Roger talk about cue 5.',
                b'Now go be the star of <i>Langley Dollar Listings.</i>')
            self.english.write_bytes(replacement)
            entry=pilot.freeze(5,(self.root,),self.output,self.profile)['episodes'][0]
            _,rows=intake.extract(self.video,self.track)
            folder=self.output/'episodes'/entry['episode']
            for row in rows:
                if row[0]==6:continue
                core.save(folder/'cues'/('%05d.json'%row[0]),{
                    'cue_id':row[0],'japanese':'既存の日本語です。',
                    'valid':True,'model_id':core.MODEL_ID,'source_sha':entry['source_sha']})
            goodfile=folder/'cues'/'00005.json'
            original_good=goodfile.read_bytes()
            for attempt in range(1,7):
                reply=('じゃあ、<i>Langley Dollar Listings</i>の主役になってろ。'
                    if attempt<=2 else
                    'さあ、<i lang="en">Langley Dollar Listings</i>の主役になって。')
                core.save(folder/'errors'/('%05d-%d.json'%(6,attempt)),{
                    'cue_id':6,'error':'Invalid Japanese/format','reply':reply})
            error_before=(folder/'errors'/'00006-3.json').read_bytes()
            with patch.object(core,'note',return_value=None):
                result=pilot.translate(entry,'{}',None,self.output,(self.root,),
                                       lambda _:self.fail('Any model call is unnecessary'),True)
            self.assertEqual(result['state'],'published_new_pilot')
            self.assertEqual((folder/'cues'/'00006.json').is_file(),True)
            recovered=core.load(folder/'cues'/'00006.json')
            self.assertEqual(recovered['recovery'],'validated_source_srt_italics')
            self.assertEqual((folder/'cues'/'00005.json').read_bytes(),original_good)
            self.assertEqual((folder/'errors'/'00006-3.json').read_bytes(),error_before)
            self.assertIn('<i>Langley Dollar Listings</i>',
                          intake.pilot_path(self.video).read_text(encoding='utf8'))

    def test_rescue_prompt_only_translates_current_and_limits_context(self):
        _,rows=intake.extract(self.video,self.track)
        for mode in (3,4,5,6):
            messages=core.recovery_prompt(rows,5,['already Japanese'],mode)
            self.assertEqual(len(messages),2)
            self.assertIn(rows[5][4],messages[1]['content'])
            self.assertIn('ONLY',messages[0]['content'])
        with self.assertRaises(ValueError):
            core.recovery_prompt(rows,5,[],7)

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
