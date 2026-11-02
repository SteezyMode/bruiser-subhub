"""Offline v011 tests: segmentation, exact mapped JA, safe checkpoints and publishing."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import semantic_groups_011 as sem
from tools import american_dad_utterance_011 as v3
from tools import american_dad_intake_009 as intake
from tools import american_dad_core_009 as core


def row(n,start,end,text):
    return (n, '00:00:00,000 --> 00:00:01,000',start,end,text)


class Unit011(unittest.TestCase):
    def test_split_sentence_and_anaphoric_response_are_grouped(self):
        source=[
          row(1,0,1400,'It is reassuring to know that'),
          row(2,1600,2800,'our new arrangement works.'),
          row(3,3000,4400,'This cannot prevent me.'),
          row(4,4600,5300,'Nothing will.'),
          row(5,9000,9600,'A separate scene.')]
        groups=sem.plan(source)
        self.assertEqual([[x[0] for x in g] for g in groups],[[1,2],[3,4],[5]])

    def test_bounded_3_cue_units_and_speaker_or_music_barrier(self):
        rows=[row(i,i*1800,(i*1800)+1400,'And another fragment')
              for i in range(1,7)]
        self.assertEqual([len(x) for x in sem.plan(rows)],[3,3])
        spoken=[row(1,0,1000,'An unfinished phrase'),
                row(2,1100,2000,'- First speaker.\n- Second speaker.'),
                row(3,2200,3000,'and a new sentence.')]
        self.assertEqual([len(x) for x in sem.plan(spoken)],[1,1,1])
        music=[row(1,0,1000,'We are looking'),row(2,1100,2100,'♪ Music ♪')]
        self.assertEqual([len(x) for x in sem.plan(music)],[1,1])

    def test_group_prompt_has_all_targets_but_no_future_non_targets(self):
        rows=[row(1,0,1200,'A FIRST sentence fragment'),
              row(2,1400,2600,'that finally ends.'),
              row(3,2800,4000,'SECRET_FUTURE_OUTSIDE_UNIT.')]
        group=sem.plan(rows)[0]
        self.assertEqual(len(group),2)
        messages=sem.unit_messages(group,prior_en=['An earlier idea'],
                                    prior_ja=['前のセリフ。'])
        blob=str(messages)
        self.assertIn('A FIRST sentence fragment',blob)
        self.assertIn('that finally ends.',blob)
        self.assertNotIn('SECRET_FUTURE_OUTSIDE_UNIT',blob)
        self.assertIn('An earlier idea',blob)
        self.assertIn('Reply',blob.replace('Respond','Reply'))

    def test_json_mapping_and_gated_density(self):
        group=[row(7,0,2000,'This begins'),
               row(8,2200,4300,'the new thought.')]
        valid=json.dumps({'7':'思いは始まる。','8':'新しい考えだ。'})
        self.assertEqual(set(sem.parse_unit_reply(valid,group,v3.accepted)),{'7','8'})
        with self.assertRaisesRegex(ValueError,'keys'):
            sem.parse_unit_reply('{"7":"これは何か。"}',group,v3.accepted)
        with self.assertRaises(ValueError):
            sem.parse_unit_reply('[]',group,v3.accepted)
        with self.assertRaisesRegex(ValueError,'dense'):
            sem.parse_unit_reply(json.dumps({'7':'この長すぎる日本語の文章を無理やり一瞬で表示するような翻訳です。',
                                             '8':'短い文章。'}),group,v3.accepted)

    def test_semantic_repeat_heuristic_catches_paraphrased_repetition(self):
        rows=[row(2,0,2000,'An opening clause'),
              row(3,2100,3900,'a closing different clause.')]
        japanese={'2':'私は明日の新しい映画を見ることが本当に楽しみで仕方がありません。',
                  '3':'明日の新しい映画を見ることが本当に楽しみで仕方がありませんよ。'}
        self.assertIn(2,sem.repeated_meaning_candidates(rows,japanese))
        self.assertTrue(sem.quality_flags(rows,japanese)['repeated'])

    def test_two_voice_cue_must_not_erase_turns(self):
        en='- I am here.\n- So am I.'
        self.assertFalse(sem.valid_speakers(en,'俺もここにいる。'))
        self.assertTrue(sem.valid_speakers(en,'俺はここだ。\n俺も。'))

    def test_source_partition_never_changes_order_or_timing(self):
        rows=[row(i,(i-1)*1300,i*1300,('The sentence continues' if i%3 else 'to a stop.'))
              for i in range(1,74)]
        out=sem.plan(rows)
        self.assertEqual([x for group in out for x in group],rows)
        self.assertTrue(all(1<=len(g)<=3 for g in out))


def source_srt(n=151):
    blocks=[]
    for i in range(n):
        a=i*2
        def clock(s):
            return '%02d:%02d:%02d,000'%(s//3600,(s//60)%60,s%60)
        if i%3==0: english='It is important that'
        elif i%3==1: english='we understand this detail.'
        else: english='This is another complete sentence.'
        blocks.append('%d\n%s --> %s\n%s'%(i+1,clock(a),clock(a+1),english))
    return ('\n\n'.join(blocks)+'\n').encode('utf8')


class Pilot011(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'media'
        self.root.mkdir()
        self.season=self.root/'American Dad'/'Season 20'
        self.season.mkdir(parents=True)
        self.video=self.season/'American.Dad.S20E10.mkv'
        self.video.write_bytes(b'dummy video bytes')
        self.source=self.season/'American.Dad.S20E10.en.srt'
        self.source.write_bytes(source_srt())
        self.track={'kind':'sidecar','path':str(self.source)}
        self.state=Path(self.tmp.name)/'scratch-v011'
        self.profile=Path(self.tmp.name)/'profile.json'
        self.profile.write_text('{"recurring_people":[]}',encoding='utf8')

    def frozen(self):
        with patch.object(intake,'tracks',return_value=self.track):
            return v3.freeze(3,(self.root,),self.state,self.profile)['episodes'][0]

    def fake(self,messages,json_mode=False):
        if json_mode:
            text=messages[-1]['content']
            section=text.split('[ALL_TARGET_CUES]\n',1)[1].split(
                '\n[/ALL_TARGET_CUES]',1)[0]
            return json.dumps({x['id']:'日本語で話しています。' for x in json.loads(section)},
                              ensure_ascii=False)
        return '短い日本語です。'

    def test_publish_full_resumable_fresh_episode(self):
        entry=self.frozen()
        with patch.object(intake,'tracks',return_value=self.track), \
             patch.object(v3,'optional_note',return_value=None):
            out=v3.generate_episode(entry,'{}',None,self.state,(self.root,),
                                    self.fake,True)
            self.assertEqual(out['state'],'published_new_utterance')
            dest=v3.sidecar(self.video)
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.read_bytes().count(b'-->'),151)
            again=v3.generate_episode(entry,'{}',None,self.state,(self.root,),
                    lambda *_args,**_kw:self.fail('Unexpected model call'),True)
            self.assertEqual(again['state'],'already_published_identical')
        self.assertEqual(self.source.read_bytes(),source_srt())
        self.assertFalse(intake.pilot_path(self.video).exists())

    def test_broken_group_json_does_not_publish_or_repeat_failed_calls(self):
        entry=self.frozen()
        seen=[]
        def invalid(messages,json_mode=False):
            seen.append(json_mode)
            if json_mode:return '{}'
            return '短い日本語です。'
        with patch.object(intake,'tracks',return_value=self.track), \
             patch.object(v3,'optional_note',return_value=None):
            out=v3.generate_episode(entry,'{}',None,self.state,(self.root,),
                                    invalid,True)
            self.assertEqual(out['state'],'incomplete')
            self.assertFalse(v3.sidecar(self.video).exists())
            before=len(seen)
            # Previously failed group attempts are immutable; never spin forever.
            repeat=v3.generate_episode(entry,'{}',None,self.state,(self.root,),
                                       invalid,True)
            self.assertEqual(repeat['state'],'incomplete')
            self.assertLess(len(seen)-before,4)

    def test_completed_japanese_is_never_replaced(self):
        self.video.with_name(self.video.stem+'.Bruiser ContextSafe v2 Japanese.ja.srt'
                             ).write_bytes(b'Existing v010 output')
        with self.assertRaisesRegex(RuntimeError,'No eligible'):
            self.frozen()

    def test_existing_new_sidecar_never_overwritten(self):
        entry=self.frozen()
        dest=v3.sidecar(self.video)
        dest.write_bytes(b'Owner made JA subtitle')
        with patch.object(intake,'tracks',return_value=self.track), \
             patch.object(v3,'optional_note',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'NEVER overwrite'):
                v3.generate_episode(entry,'{}',None,self.state,(self.root,),
                    lambda *_args,**_kw:self.fail('no model call'),True)
        self.assertEqual(dest.read_bytes(),b'Owner made JA subtitle')

    def test_source_tamper_and_manifest_fingerprint_block(self):
        entry=self.frozen()
        with patch.object(intake,'catalog',side_effect=AssertionError('reselect')):
            self.assertEqual(entry,v3.freeze(3,(self.root,),self.state,
                                             self.profile)['episodes'][0])
        with self.assertRaisesRegex(RuntimeError,'identity mismatch'):
            v3.freeze(2,(self.root,),self.state,self.profile)
        self.source.write_bytes(source_srt().replace(b'It is',b'It was'))
        with patch.object(intake,'tracks',return_value=self.track), \
             patch.object(v3,'optional_note',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'Original English'):
                v3.generate_episode(entry,'{}',None,self.state,(self.root,),
                                    self.fake,False)

    def test_optional_series_context_one_schema_repair(self):
        entry=self.frozen()
        replies=[{'names':'Stan','terms':[],'notes':[],'caveats':[]},
                 {'names':['Stan'], 'terms':[],'notes':[],'caveats':[]}]
        calls=[]
        def ask(msg,json_mode=False):
            calls.append(msg)
            return json.dumps(replies.pop(0))
        note=v3.optional_note('series','American Dad',
                [Path(entry['source_path'])],self.state,ask)
        self.assertEqual(note['note']['names'],['Stan'])
        self.assertEqual(len(calls),2)
        self.assertIn('SCHEMA CORRECTION',str(calls[1]))
        self.assertTrue((self.state/'context'/'series'/'american-dad.json').is_file())

    def test_wrapper_does_not_deploy_services(self):
        import subprocess
        path=Path(__file__).resolve().parent/'tools/run_utterance_pilot_011.sh'
        run=subprocess.run(['bash','-n',str(path)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        contents=path.read_text(encoding='utf8')
        self.assertIn('--episodes 3',contents)
        self.assertNotIn('systemctl restart',contents)
        self.assertNotIn('docker restart',contents)


if __name__=='__main__':
    unittest.main()
