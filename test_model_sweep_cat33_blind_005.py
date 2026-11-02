"""Synthetic-only tests for fixed final CAT 3.3B source and blind adjudication."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import model_benchmark as old
from tools import model_sweep_cat33_005 as cat
from tools import model_sweep_005 as suite
from tools import blind_model_sweep_005 as blind


class FinalCatAndBlindTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)/'pilot'
        self.root=self.base/'subhub1-state'
        self.base.mkdir(parents=True)
        db=service.Store(self.root)
        src=('\n\n'.join(
            f"{i}\n00:{i//60:02d}:{i%60:02d},000 --> "
            f"00:{(i+1)//60:02d}:{(i+1)%60:02d},000\n"
            f"Synthetic original {i}."
            for i in range(1,750))+'\n').encode()
        self.digest=hashlib.sha256(src).hexdigest()
        db.add(suite.JOB_ID,self.base/'fictional.mkv',src,'eng')
        db.state(suite.JOB_ID,'published')
        db.cn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def groups(self):
        with patch.object(suite,'SOURCE_SHA',self.digest):
            return suite.dataset(self.root)

    def test_cat_final_is_not_beta_and_uses_native_source_instruction(self):
        self.assertEqual(cat.MODEL,'cyberagent/CAT-Translate-3.3b')
        self.assertNotIn('beta',cat.MODEL.casefold())
        self.assertEqual(cat.CAT_PROMPT,
                         'Translate the following English text into Japanese.\n\n')
        self.assertEqual(cat.QUANT,'bitsandbytes_nf4_4bit_float16')
        self.assertEqual(cat.MAX_NEW_TOKENS,512)

    def test_cat_tokenizer_dependency_preflight_fails_before_downloads(self):
        # These two modules were missing in the actual owner-run log.
        class Stub:
            __version__='test-version'
        expected=['sentencepiece','google.protobuf']
        found=[]
        def importer(name):
            found.append(name)
            return Stub()
        got=cat.tokenizer_dependency_versions(importer=importer)
        self.assertEqual(found,expected)
        self.assertEqual(got,{'sentencepiece':'test-version',
                              'protobuf':'test-version'})
        def absent(name):
            if name=='sentencepiece':
                raise ModuleNotFoundError('simulated missing sentencepiece')
            return Stub()
        with self.assertRaisesRegex(RuntimeError,
                                    'Missing CAT tokenizer dependency sentencepiece'):
            cat.tokenizer_dependency_versions(importer=absent)
        def no_protobuf(name):
            if name=='google.protobuf':
                raise ImportError('simulated missing protobuf')
            return Stub()
        with self.assertRaisesRegex(RuntimeError,
                                    'Missing CAT tokenizer dependency protobuf'):
            cat.tokenizer_dependency_versions(importer=no_protobuf)

    def test_final_cat_64_fake_outputs_and_no_sqlite_modification(self):
        groups=self.groups()
        before=(self.root/'jobs.sqlite3').stat().st_size
        seen=[]
        def fake(model,tokenizer,english):
            seen.append(english)
            return '自然な字幕。',{'output_tokens':5}
        entries,calls,stopped=cat.run(self.base,self.root,groups,
                                      model=object(),tokenizer=object(),call=fake)
        self.assertIsNone(stopped)
        self.assertEqual(len(entries),64)
        self.assertEqual(len(calls),64)
        self.assertTrue(all(r['valid_japanese'] for r in entries))
        self.assertEqual(len(seen),64)
        self.assertEqual((self.root/'jobs.sqlite3').stat().st_size,before)

    def test_cat_fails_fast_on_bad_cuda_response(self):
        def fail(*a):raise ValueError('synthetic CUDA OOM')
        entries,calls,reason=cat.run(self.base,self.root,self.groups(),
                                      object(),object(),call=fail)
        self.assertEqual(len(entries),3)
        self.assertEqual(reason,'three_consecutive_model_errors')

    def test_blind_pack_hides_model_names_and_shuffles_individually(self):
        groups=self.groups()
        cues=[r for g in groups for r in g]
        data=[]
        for arm in ('tuned','cat33_final','cat7','hy7','google12'):
            data.append({
                'arm':arm,
                'source_sha256':self.digest,
                'entries':[{
                    'cue_id':row['cue_id'],
                    'english':row['english'],'timing':row['timing'],
                    'candidate_japanese':'自然な日本語です。',
                } for row in cues]
            })
        pack,key=blind.build(data)
        self.assertEqual(pack['cue_count'],64)
        self.assertEqual(pack['arm_count'],5)
        self.assertNotIn('cat33_final',str(pack))
        self.assertNotIn('hy7',str(pack))
        self.assertIn('hy7',str(key))
        self.assertEqual(pack['entries'][0]['candidates'][0]['review']
                         ['semantic_fidelity_0_to_4'],None)
        other,key2=blind.build(data)
        self.assertEqual(pack,other)
        self.assertEqual(key,key2)
        for r in pack['entries']:
            self.assertEqual(len(r['candidates']),5)
            self.assertEqual(set(key['map_by_cue_id'][str(r['cue_id'])]),
                             {'A','B','C','D','E'})

    def test_blinding_refuses_mismatched_sources_and_incomplete_run(self):
        # collect reads JSON from disk to verify source/ID coverage.
        import json
        x={'schema':'bruiser-private-model-sweep-005-v1',
           'complete':True,'arm':'tuned','source_sha256':'sha',
           'entries':[{'cue_id':i,'english':'invented','timing':'00:00:01 --> 00:00:02',
                       'candidate_japanese':'適切です。'} for i in range(64)]}
        one=Path(self.tmp.name)/'one.json'
        two=Path(self.tmp.name)/'two.json'
        one.write_text(json.dumps(x))
        y={**x,'arm':'cat7','source_sha256':'another'}
        two.write_text(json.dumps(y))
        with self.assertRaisesRegex(ValueError,'source SHA mismatch'):
            blind.collect([one,two])
        y['source_sha256']='sha'
        y['complete']=False
        two.write_text(json.dumps(y))
        with self.assertRaisesRegex(ValueError,'Arm incomplete'):
            blind.collect([one,two])
        with self.assertRaises(FileExistsError):
            blind.private_create(one,{'could':'never overwrite existing'})

if __name__=='__main__':
    unittest.main()
