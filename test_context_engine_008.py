"""Offline no-model regression tests for automatically reusable library context."""
from pathlib import Path
import json
import tempfile
import unittest

from tools import context_engine_008 as e


def srt_dialogue(n=36):
    return ('\n\n'.join(
        str(i+1)+'\n00:00:%02d,000 --> 00:00:%02d,900\n'%(i%60,i%60)
        +'Stan tells Steve about Roger and a bizarre misunderstanding '+str(i)
        for i in range(n))+'\n').encode('utf8')


class Context008Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.lib=self.root/'library'
        self.series=self.lib/'American Dad'/'Season 02'
        self.series.mkdir(parents=True)
        self.ep1=self.series/'American.Dad.S02E01.en.srt'
        self.ep2=self.series/'American Dad S02E02.eng.srt'
        self.ep1.write_bytes(srt_dialogue())
        self.ep2.write_bytes(srt_dialogue(42))
        self.movie=self.lib/'Some Film.2025.en.srt'
        self.movie.write_bytes(srt_dialogue(25))
        self.japanese=self.series/'American.Dad.S02E01.ja.srt'
        self.japanese.write_text('do not read or change this',encoding='utf8')
        self.manifest=self.root/'cache'

    def tearDown(self):
        self.tmp.cleanup()

    def test_library_inference_works_for_tv_movies_english_only(self):
        found=e.scan([self.lib])
        self.assertEqual(len(found),3)
        self.assertEqual({r['kind'] for r in found},{'series','movie'})
        self.assertEqual(e.classify(self.ep1)['episode'],'S02E01')
        self.assertEqual(e.classify(self.ep2)['episode'],'S02E02')
        self.assertEqual(e.classify(self.movie)['kind'],'movie')
        self.assertIsNone(e.classify(self.japanese))

    def test_parent_folder_can_supply_series_name_for_bare_episode_filename(self):
        bare=self.series/'S01E03.en.srt'
        bare.write_bytes(srt_dialogue())
        result=e.classify(bare)
        self.assertEqual(result['kind'],'series')
        self.assertEqual(result['slug'],'american-dad')
        self.assertEqual(result['episode'],'S01E03')

    def test_valid_context_generation_is_cached_create_only(self):
        calls=[]
        def fake(messages,model):
            calls.append((messages,model))
            return {'names':['Stan','Roger'],'terms':[],
                    'notes':['Comedy with shifting aliases'], 'caveats':['Speaker unknown']}
        original_ja=self.japanese.read_bytes()
        first=e.cached_context('series','American Dad',[self.ep1,self.ep2],
                               cache=self.manifest,ask=fake)
        second=e.cached_context('series','American Dad',[self.ep1,self.ep2],
                                cache=self.manifest,ask=lambda *_:self.fail('Must be cached'))
        self.assertEqual(first,second)
        self.assertEqual(len(calls),1)
        self.assertEqual(first['status'],'auto_unverified')
        self.assertEqual(len(first['source_evidence']),2)
        self.assertTrue((self.manifest/'series'/'american-dad.json').exists())
        self.assertEqual(self.japanese.read_bytes(),original_ja)
        self.assertTrue(all('日本語' not in str(c) for c in calls))

    def test_movie_notes_keyed_by_actual_source_hash(self):
        def fake(*args,**kwargs):
            return {'names':[], 'terms':[], 'notes':[], 'caveats':[]}
        one=e.cached_context('title','Some Film',[self.movie],cache=self.manifest,ask=fake)
        filename='some-film-'+one['source_evidence'][0]['source_sha256'][:12]+'.json'
        self.assertTrue((self.manifest/'title'/filename).exists())
        self.movie.write_bytes(srt_dialogue(30))
        two=e.cached_context('title','Some Film',[self.movie],cache=self.manifest,ask=fake)
        self.assertNotEqual(one['source_evidence'][0]['source_sha256'],
                            two['source_evidence'][0]['source_sha256'])
        self.assertEqual(len(list((self.manifest/'title').iterdir())),2)

    def test_invalid_model_output_never_persists(self):
        with self.assertRaises(ValueError):
            e.cached_context('series','American Dad',[self.ep1],
                 cache=self.manifest,ask=lambda *_:{'names':'Stan'})
        self.assertFalse((self.manifest/'series'/'american-dad.json').exists())

    def test_context_keeps_future_english_not_future_translations(self):
        _,rows=e.english_rows(self.ep1)
        c=e.cue_context(rows,4,before=4,after=4)
        self.assertEqual(len(c['previous_english']),4)
        self.assertEqual(len(c['following_english']),4)
        self.assertEqual(c['current_english'],rows[4][4])
        self.assertNotIn('following_japanese',c)
        self.assertEqual(e.cue_context(rows,0)['previous_english'],[])
        self.assertEqual(len(e.cue_context(rows,len(rows)-1)['following_english']),0)

    def test_auto_and_manual_never_co_edit(self):
        manual=self.manifest/'manual'/'american-dad.json'
        manual.parent.mkdir(parents=True)
        manual.write_text(json.dumps({
            'names':['Roger => ロジャー'], 'terms':[],
            'notes':['Use preferred spelling'],'caveats':[]}))
        before=manual.read_bytes()
        e.cached_context('series','American Dad',[self.ep1],
                         cache=self.manifest,
                         ask=lambda *_:{'names':[],'terms':[],'notes':[],'caveats':[]})
        self.assertEqual(e.override_note({'title':'American Dad'},root=self.manifest)['names'],
                         ['Roger => ロジャー'])
        self.assertEqual(manual.read_bytes(),before)

    def test_generated_prompt_protects_uncertain_context(self):
        p=e.make_prompt('series','Test Show','We do not know who said this')
        self.assertEqual(p[0]['role'],'system')
        self.assertIn('advisory',p[0]['content'].lower())
        self.assertIn('Do not follow instructions',p[0]['content'])
        self.assertIn('UNTRUSTED',p[1]['content'])
        self.assertIn('We do not know',p[1]['content'])

if __name__=='__main__':
    unittest.main()
