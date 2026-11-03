"""Offline verification for private S19E04 editorial overlay and non-overwrite."""
import contextlib
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import s19e04_apply_private_editorial as editorial
from tools import repair_s19e04 as repair


def clip_rows(n=392):
    def clock(ms):
        s=ms//1000
        return f'{s//3600:02d}:{(s//60)%60:02d}:{s%60:02d},{ms%1000:03d}'
    return [(id,
             f'{clock((id-1)*3000)} --> {clock((id-1)*3000+2700)}',
             (id-1)*3000,(id-1)*3000+2700,f'English source cue {id}')
            for id in range(1,n+1)]


class PrivateS19EditorialTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.video=self.root/'American.Dad.S19E04.mkv'
        self.video.write_bytes(b'media original')
        self.state=self.root/'private'
        self.rows=clip_rows()
        self.jp={str(r[0]):'自然な字幕です。' for r in self.rows}
        for id in editorial.REQUIRED_CUES:
            self.jp[str(id)]='前の台詞から未来の台詞まで延々と入り込み字幕を読みきれない長すぎる文章です。'
        self.english=service.render_srt(
            self.rows,{str(r[0]):r[4] for r in self.rows})
        self.old=service.render_srt(self.rows,self.jp)
        self.pilot=repair.intake.pilot_path(self.video)
        self.pilot.write_bytes(self.old)
        self.payload={
            'schema':editorial.SCHEMA,'episode':'S19E04',
            'total_cues':392,'reviewed_cues':27,
            'entries':[{
                'cue_id':id,
                'english_sha256':editorial.sha(self.rows[id-1][4]),
                'original_japanese_sha256':editorial.sha(self.jp[str(id)]),
                'japanese':'自然な字幕に直した。',
            } for id in sorted(editorial.REQUIRED_CUES)]}
        self.logs=[]

    def pair(self,video,roots):
        self.assertEqual(video,self.video)
        return self.rows,dict(self.jp),self.english,self.old

    def run_editorial(self,apply=False,payload=None):
        with patch.object(editorial.core,'locks',
                          return_value=contextlib.nullcontext()):
            return editorial.publish(
                payload or self.payload,state=self.state,roots=(self.root,),
                selector=lambda roots:self.video,pair_loader=self.pair,
                apply=apply,log=lambda *x,**kw:self.logs.append(x))

    def test_private_preview_preserves_all_originals(self):
        self.assertEqual(self.run_editorial(),'private_ready')
        previews=list(self.state.glob('editorial-preview-*.ja.srt'))
        self.assertEqual(len(previews),1)
        out=service.parse_srt(previews[0].read_bytes())
        self.assertEqual(len(out),392)
        self.assertEqual([x[:4] for x in out],[x[:4] for x in self.rows])
        self.assertEqual(self.pilot.read_bytes(),self.old)
        self.assertEqual(self.video.read_bytes(),b'media original')
        self.assertFalse(list(self.root.glob('*Curated Japanese v2.ja.srt')))

    def test_publishes_separate_versioned_fully_qad_track_create_only(self):
        self.assertEqual(self.run_editorial(apply=True),'published')
        target=self.video.with_name(
            self.video.stem+'.'+editorial.OUTPUT_SUFFIX)
        self.assertTrue(target.is_file())
        old=target.read_bytes()
        self.assertEqual(len(service.parse_srt(old)),392)
        self.assertEqual(self.run_editorial(apply=True),'published')
        self.assertEqual(target.read_bytes(),old)
        self.assertEqual(self.pilot.read_bytes(),self.old)
        self.assertEqual(self.video.read_bytes(),b'media original')
        self.assertFalse(list(self.state.glob('cues/*.json')))
        self.assertTrue(any(x[0]=='S19E04_EDITORIAL_PUBLISHED'
                            for x in self.logs))

    def test_reuses_existing_v1_v2_checkpoint_for_other_episode_cues(self):
        self.assertEqual(self.run_editorial(),'private_ready')
        manifest=json.loads((self.state/'manifest.json').read_text())
        baseline=repair.intake.sha(
            json.dumps(manifest,sort_keys=True).encode())
        check=self.state/'cues'/'00100.json'
        repair.save_json(check,{
            'cue_id':100,'manifest_sha':baseline,
            'japanese':'保存した校正済み字幕。','attempt':1})
        self.assertEqual(self.run_editorial(apply=True),'published')
        file=self.video.with_name(
            self.video.stem+'.'+editorial.OUTPUT_SUFFIX)
        parsed=service.parse_srt(file.read_bytes())
        self.assertEqual(parsed[99][4],'保存した校正済み字幕。')
        self.assertEqual(repair.checkpoint(self.state,100,baseline),
                         '保存した校正済み字幕。')

    def test_wrong_original_source_fingerprint_refuses_publication(self):
        payload=json.loads(json.dumps(self.payload))
        payload['entries'][0]['english_sha256']='a'*64
        with self.assertRaisesRegex(RuntimeError,'English input fingerprint'):
            self.run_editorial(apply=True,payload=payload)
        self.assertFalse(list(self.root.glob('*Curated Japanese v2.ja.srt')))

    def test_original_japanese_fingerprint_refuses_changed_episode(self):
        payload=json.loads(json.dumps(self.payload))
        payload['entries'][0]['original_japanese_sha256']='f'*64
        with self.assertRaisesRegex(RuntimeError,'Original Japanese fingerprint'):
            self.run_editorial(apply=True,payload=payload)
        self.assertEqual(self.pilot.read_bytes(),self.old)

    def test_extra_or_duplicate_or_missing_cue_refused(self):
        for transformation in ('missing','duplicate','extra'):
            item=json.loads(json.dumps(self.payload))
            if transformation=='missing':item['entries'].pop()
            elif transformation=='duplicate':
                item['entries'][-1]=item['entries'][0].copy()
            else:item['entries'][-1]['cue_id']=999
            with self.subTest(transformation=transformation):
                with self.assertRaises(ValueError):
                    editorial.validate_payload(item)

    def test_overlong_editorial_does_not_publish_even_with_hashes_valid(self):
        payload=json.loads(json.dumps(self.payload))
        payload['entries'][0]['japanese']='字幕が長すぎて視聴できない。'*10
        self.assertEqual(self.run_editorial(apply=True,payload=payload),
                         'held')
        self.assertFalse(list(self.root.glob('*Curated Japanese v2.ja.srt')))
        self.assertTrue(any(x[0]=='S19E04_EDITORIAL_HOLD'
                            for x in self.logs))

    def test_crash_after_private_preview_before_final_published_safe(self):
        self.assertEqual(self.run_editorial(apply=False),'private_ready')
        self.assertEqual(self.run_editorial(apply=True),'published')
        self.assertEqual(self.pilot.read_bytes(),self.old)

    def test_no_english_or_original_dialogue_in_console_logs(self):
        self.run_editorial(apply=True)
        log=json.dumps(self.logs,ensure_ascii=False)
        self.assertNotIn('English source cue',log)
        self.assertNotIn('前の台詞から未来',log)


if __name__=='__main__':
    unittest.main()
