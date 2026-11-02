"""No-Ollama tests for real S19E04 versioned, resumable QA repair."""
import contextlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest

import service
from tools import repair_s19e04 as repair


def rows(n=151):
    def tm(s):
        return '%02d:%02d:%02d,000'%(s//3600,(s//60)%60,s%60)
    return [(i+1,f'{tm(i*3)} --> {tm(i*3+2)}',
             i*3000,i*3000+2000,'EN_CURRENT_ID_%d'%(i+1))
            for i in range(n)]


class S19RepairTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.video=self.root/'American.Dad.S19E04.mkv'
        self.video.write_bytes(b'original-video-untouched')
        self.state=self.root/'private'
        self.pilot=self.video.with_name(
            self.video.stem+'.Bruiser Pilot Japanese.ja.srt')
        self.en=rows()
        original={str(r[0]):'自然な日本語です。' for r in self.en}
        original['52']='先に全部説明してしまうけれど次の台詞を余計に含めた長いロジャーの説明文がここに入っています。'
        original['53']='次の台詞を余計に含めた長いロジャーの説明文がここに入っています。'
        original['54']='おかしな翻訳です。'
        self.ja=original
        self.en_raw=service.render_srt(
            self.en,{str(r[0]):r[4] for r in self.en})
        self.ja_raw=service.render_srt(self.en,self.ja)
        self.pilot.write_bytes(self.ja_raw)
        self.calls=[]

    def fake_pair(self,video,roots):
        self.assertEqual(video,self.video)
        return self.en,dict(self.ja),self.en_raw,self.ja_raw

    def fake_ask(self,messages):
        combined=str(messages)
        self.assertIn('[CURRENT_ENGLISH]',combined)
        self.assertNotIn('EN_CURRENT_ID_51',combined if 'EN_CURRENT_ID_52' in combined else 'no')
        self.assertNotIn('EN_CURRENT_ID_53',combined if 'EN_CURRENT_ID_52' in combined else 'no')
        self.calls.append(combined)
        return '自然な日本語です。'

    def invoke(self,ask=None,publish=True):
        with patch.object(repair.core,'locks',return_value=contextlib.nullcontext()):
            return repair.execute(
                state=self.state,roots=(self.root,),
                selector=lambda roots:self.video,
                pair_loader=self.fake_pair,ask=ask or self.fake_ask,
                publish=publish,max_minutes=5,log=lambda *x:None)

    def test_qa_flags_realistic_old_oversized_overlap(self):
        found=repair.detected_ids(self.en,self.ja)
        self.assertIn(52,found)
        self.assertTrue(repair.q.future_overlap(
            self.ja['52'],self.ja['53']))
        self.assertNotIn(55,found)

    def test_versioned_new_track_keeps_original_unchanged(self):
        self.assertEqual(self.invoke(),'published')
        target=repair.output(self.video)
        self.assertTrue(target.exists())
        self.assertTrue(target.name.endswith('.Bruiser Readability Repair v1 Japanese.ja.srt'))
        self.assertEqual(self.pilot.read_bytes(),self.ja_raw)
        self.assertEqual(self.video.read_bytes(),b'original-video-untouched')
        new=service.parse_srt(target.read_bytes())
        self.assertEqual(len(new),151)
        self.assertEqual([x[:4] for x in new],[x[:4] for x in self.en])
        self.assertNotEqual(new[51][4],self.ja['52'])
        self.assertEqual(new[54][4],self.ja['55'])
        self.assertEqual(repair.gate.audit([
            {'cue_id':r[0],'timing':r[1],
             'start_ms':r[2],'end_ms':r[3],
             'english':r[4],'japanese':new[i][4]}
            for i,r in enumerate(self.en)])['flagged_cues'],0)
        previous=target.read_bytes()
        self.calls.clear()
        self.assertEqual(self.invoke(ask=lambda _:self.fail('No repeated model calls')),
                         'published')
        self.assertEqual(target.read_bytes(),previous)

    def test_unresolved_bad_model_output_never_publishes(self):
        broken='この字幕は異常に長すぎる。'*18
        self.assertEqual(self.invoke(ask=lambda _:broken),'held')
        self.assertFalse(repair.output(self.video).exists())
        self.assertEqual(self.pilot.read_bytes(),self.ja_raw)
        self.assertEqual(self.video.read_bytes(),b'original-video-untouched')
        self.assertTrue(list(self.state.glob('report-*.json')))

    def test_power_interruption_resumes_saved_cues_without_replay(self):
        counter=[0]
        def first(messages):
            counter[0]+=1
            if counter[0]==2:
                raise KeyboardInterrupt()
            return '自然な日本語です。'
        with self.assertRaises(KeyboardInterrupt):
            self.invoke(ask=first)
        saved=list((self.state/'cues').glob('*.json'))
        self.assertEqual(len(saved),1)
        self.assertFalse(repair.output(self.video).exists())
        self.calls.clear()
        self.assertEqual(self.invoke(),'published')
        self.assertGreaterEqual(len(self.calls),1)
        self.assertEqual(self.pilot.read_bytes(),self.ja_raw)

    def test_private_manifest_rejects_changed_original(self):
        self.invoke(publish=False)
        changed=self.ja_raw.replace(b'\x00',b'x')+b'\n'
        self.ja_raw=changed
        with self.assertRaisesRegex(RuntimeError,'identity changed'):
            self.invoke(publish=False)

    def test_atomic_create_only_does_not_leave_half_written_srt(self):
        target=self.root/'new.ja.srt'
        with patch.object(repair.os,'link',side_effect=OSError('interrupted')):
            with self.assertRaisesRegex(OSError,'interrupted'):
                repair.create_exact(target,b'complete')
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob('*.stage-*')),[])
        self.assertTrue(repair.create_exact(target,b'complete'))
        self.assertFalse(repair.create_exact(target,b'complete'))
        with self.assertRaisesRegex(RuntimeError,'differs'):
            repair.create_exact(target,b'modified')
        self.assertEqual(target.read_bytes(),b'complete')

    def test_only_this_episode_and_not_other_media(self):
        self.assertEqual(repair.EPISODE,(19,4))
        self.assertEqual(repair.VERSION,'Bruiser Readability Repair v1 Japanese.ja.srt')
        self.assertIn(54,repair.SEMANTIC_REVIEW)


if __name__=='__main__':
    unittest.main()
