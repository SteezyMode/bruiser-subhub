"""Synthetic regression for generic context isolation and fresh American Dad v010."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import subtitle_quality_010 as q
from tools import american_dad_contextsafe_010 as v2
from tools import american_dad_intake_009 as intake
from tools import american_dad_core_009 as core


def source_srt(n=151):
    blocks=[]
    for i in range(n):
        a=i*2
        b=a+1
        def clock(s):return '00:%02d:%02d,000'%(s//60,s%60)
        blocks.append('%d\n%s --> %s\nEnglish current source cue %d only.'%
                      (i+1,clock(a),clock(b),i))
    return ('\n\n'.join(blocks)+'\n').encode('utf8')


class Quality010Unit(unittest.TestCase):
    def test_prompt_never_has_raw_future_english(self):
        rows=[
            (1,'timing',0,1500,'FIRST_SOURCE_CURRENT'),
            (2,'timing',1500,3000,'SECOND_SOURCE_CURRENT'),
            (3,'timing',3000,4500,'SECRET_FUTURE_ENGLISH'),
        ]
        msg=q.cue_messages(rows,1,['前の日本語。'],
                           series_note='Series context',
                           title_note='Episode summary',
                           series_bible='Roger has aliases')
        blob=str(msg)
        self.assertIn('SECOND_SOURCE_CURRENT',blob)
        self.assertIn('FIRST_SOURCE_CURRENT',blob)
        self.assertNotIn('SECRET_FUTURE_ENGLISH',blob)
        self.assertIn('Roger has aliases',blob)
        repair=q.cue_messages(rows,1,['previous Japanese'],repair=True)
        text=str(repair)
        self.assertNotIn('FIRST_SOURCE_CURRENT',text)
        self.assertNotIn('SECRET_FUTURE_ENGLISH',text)
        self.assertNotIn('previous Japanese',text)

    def test_reading_density_warn_vs_severe(self):
        self.assertFalse(q.length_risk('大丈夫',0,1500)['severe_density'])
        self.assertTrue(q.length_risk('非常に長すぎる字幕が一瞬で出て今すぐ消えるのは読み切れない',
                                       0,500)['severe_density'])
        self.assertEqual(q.visible_chars('<i>こんにちは</i>'),5)
        self.assertEqual(q.visible_chars('{\\an8}　こんにちは '),5)

    def test_detects_long_future_cue_repeated_early_not_common_names(self):
        future='あとで全員に会って話すことにしようよ'
        leaked='そうだね、もう帰ろう。'+future
        self.assertTrue(q.future_overlap(leaked,future))
        self.assertFalse(q.future_overlap('はい、スタン','スタン'))
        self.assertFalse(q.future_overlap('また後で','また後で'))
        self.assertFalse(q.future_overlap('違う意味の会話です','来週は旅行に行くことにします'))
        rows=[(1,'',0,1000,'A'),(2,'',1000,2000,'B'),(3,'',2000,3000,'C')]
        self.assertEqual(q.overlap_ids(rows,{'1':leaked,'2':future,'3':'了解。'}),{1})

    def test_warn_does_not_automatically_decline_meaning(self):
        result=q.length_risk('約束してほしい、今は帰らないで。',0,2100)
        self.assertFalse(result['severe_density'])


class AmericanDad010Integration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.dir=Path(self.tmp.name)
        self.root=self.dir/'media'
        self.season=self.root/'American Dad'/'Season 20'
        self.season.mkdir(parents=True)
        self.video=self.season/'American.Dad.S20E01.mkv'
        self.video.write_bytes(b'not real media, offline fixture')
        self.source=self.season/'American.Dad.S20E01.en.srt'
        self.source.write_bytes(source_srt())
        self.track={'kind':'sidecar','path':str(self.source)}
        self.state=self.dir/'test-010-private'
        self.profile=self.dir/'profile.json'
        self.profile.write_text('{"recurring_people":[]}',encoding='utf8')

    def tearDown(self):
        self.tmp.cleanup()

    def freeze(self):
        with patch.object(intake,'tracks',return_value=self.track):
            return v2.freeze(3,(self.root,),self.state,self.profile)

    def test_new_source_manifest_and_old_009_pilot_protection(self):
        frozen=self.freeze()
        self.assertEqual(len(frozen['episodes']),1)
        self.assertEqual(frozen['schema'],v2.SCHEMA)
        self.assertEqual(frozen['quality_gate_sha'],v2.module_hash())
        self.assertNotIn('raw',frozen['episodes'][0])
        with patch.object(intake,'catalog',side_effect=AssertionError('Reselected')):
            self.assertEqual(frozen,v2.freeze(3,(self.root,),self.state,self.profile))
        with self.assertRaisesRegex(RuntimeError,'identity changed'):
            v2.freeze(4,(self.root,),self.state,self.profile)

    def test_existing_009_ja_is_not_reused_or_overwritten(self):
        old=intake.pilot_path(self.video)
        old.write_bytes(b'Old pilot was already approved for test')
        with self.assertRaisesRegex(RuntimeError,'No fresh episodes'):
            self.freeze()
        self.assertEqual(old.read_bytes(),b'Old pilot was already approved for test')
        self.assertFalse(v2.sidecar(self.video).exists())

    def test_full_episode_generates_quality_checked_v2_and_resumes(self):
        manifest=self.freeze()
        item=manifest['episodes'][0]
        calls=[]
        def translate(messages):
            calls.append(messages)
            return '日本語の会話です。'
        with patch.object(intake,'tracks',return_value=self.track), \
             patch.object(core,'note',return_value=None):
            result=v2.generate_episode(item,'{}',None,self.state,(self.root,),
                                       translate,True)
            self.assertEqual(result['state'],'published_new_contextsafe')
            self.assertEqual(len(calls),151)
            self.assertTrue(v2.sidecar(self.video).exists())
            original=v2.sidecar(self.video).read_bytes()
            self.assertEqual(original.count(b'-->'),151)
            resume=v2.generate_episode(item,'{}',None,self.state,(self.root,),
                                       lambda _:self.fail('No retranslation'),True)
            self.assertEqual(resume['state'],'already_published_identical')
            self.assertEqual(v2.sidecar(self.video).read_bytes(),original)
            self.assertEqual(self.source.read_bytes(),source_srt())
            self.assertFalse(intake.pilot_path(self.video).exists())
            self.assertEqual(len(list((self.state/'episodes'/item['episode']/'cues').glob('*.json'))),151)

    def test_future_leakage_is_repaired_only_in_flagged_cue(self):
        item=self.freeze()['episodes'][0]
        total=[]
        future='明日全員で海へ行く予定を立てようよ。'
        leak='わかった、家に戻りましょう。'+future
        def translate(messages):
            content=messages[-1]['content']
            if 'targeted correction' in messages[0]['content']:
                total.append('repair')
                return 'そうしましょう。'
            number=len([x for x in total if x=='main'])
            total.append('main')
            if number==5:return leak
            if number==6:return future
            return '普通の会話です。'
        with patch.object(intake,'tracks',return_value=self.track), \
             patch.object(core,'note',return_value=None):
            result=v2.generate_episode(item,'{}',None,self.state,(self.root,),
                                       translate,True)
        self.assertEqual(result['state'],'published_new_contextsafe')
        self.assertEqual(total.count('main'),151)
        self.assertEqual(total.count('repair'),1)
        folder=self.state/'episodes'/item['episode']
        self.assertEqual(core.load(folder/'repairs'/'00006.json')['japanese'],'そうしましょう。')
        original=core.load(folder/'cues'/'00006.json')
        self.assertEqual(original['japanese'],leak)
        completed=v2.sidecar(self.video).read_text(encoding='utf8')
        self.assertIn('そうしましょう。',completed)
        self.assertNotIn(leak,completed)

    def test_extreme_density_failed_repairs_hold_and_keep_private(self):
        item=self.freeze()['episodes'][0]
        long='この文章は非常に長すぎるのでとても短い間に表示されても誰もきちんと読むことができません。'
        with patch.object(intake,'tracks',return_value=self.track), \
             patch.object(core,'note',return_value=None):
            result=v2.generate_episode(item,'{}',None,self.state,(self.root,),
                                       lambda _:long,True)
        self.assertEqual(result['state'],'held_for_quality')
        self.assertFalse(v2.sidecar(self.video).exists())
        self.assertTrue(result['unresolved_ids'])
        folder=self.state/'episodes'/item['episode']
        self.assertGreaterEqual(len(list(folder.glob('quality-v2-*.json'))),1)

    def test_existing_published_track_never_overwritten(self):
        item=self.freeze()['episodes'][0]
        target=v2.sidecar(self.video)
        target.write_bytes(b'owner created different track')
        with patch.object(intake,'tracks',return_value=self.track):
            with self.assertRaisesRegex(RuntimeError,'never overwrite'):
                v2.generate_episode(item,'{}',None,self.state,(self.root,),
                                    lambda _:self.fail('no model calls'),True)
        self.assertEqual(target.read_bytes(),b'owner created different track')

    def test_shell_wrapper_syntax_and_no_service_deploy(self):
        import subprocess
        path=Path(__file__).resolve().parent/'tools/run_contextsafe_pilot_010.sh'
        out=subprocess.run(['bash','-n',str(path)],capture_output=True,text=True)
        self.assertEqual(out.returncode,0,out.stderr)
        code=path.read_text(encoding='utf8')
        self.assertIn('--episodes 3',code)
        self.assertIn('--publish',code)
        self.assertNotIn('systemctl restart',code)

if __name__=='__main__':
    unittest.main()
