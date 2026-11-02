"""No-model tests for Japanese readability holds, checkpoint + power-loss safety."""
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

import main
import service
from tools import daily_worker
from tools import subtitle_publish_gate as gate


def source(n=20):
    def t(i):return '%02d:%02d:%02d,000'%(i//3600,(i//60)%60,i%60)
    return ('\n\n'.join(f'{i+1}\n{t(i*3)} --> {t(i*3+2)}\nHello there.'
                       for i in range(n))+'\n').encode('utf8')


def good(n):return {str(i):'自然な日本語です。' for i in range(1,n+1)}


class PublishGateTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.media=self.root/'media'
        self.media.mkdir()
        self.video=self.media/'American.Dad.S20E01.mkv'
        self.video.write_bytes(b'example video')
        self.state=self.root/'state'
        self.jid='daily-american-dad-s20e01-001122334455'

    def setup_store(self,translations=None):
        store=service.Store(self.state)
        store.add(self.jid,self.video,source(),'eng',
                  scope='daily',prior=translations or good(20))
        store.state(self.jid,'translated')
        return store

    def clean_patch(self):
        return patch.multiple(service,
            secure_video=lambda _:None,
            audio_language=lambda _:'eng')

    def test_normal_cues_are_accepted_and_overlong_with_future_leak_held(self):
        translations=good(20)
        rows=[{'cue_id':int(i),'timing':'00:00:00,000 --> 00:00:02,000',
               'start_ms':(int(i)-1)*3000,'end_ms':(int(i)-1)*3000+2000,
               'english':'Hello there.','japanese':text}
              for i,text in translations.items()]
        report=gate.audit(rows)
        self.assertFalse(report['publication_held'])
        self.assertEqual(report['cues_checked'],20)
        self.assertEqual(report['flagged_cues'],0)
        rows[2]['japanese']='ロジャーは次の場面でもずっと長い話を続けていてここには入りきらない。'
        rows[3]['japanese']='次の場面でもずっと長い話を続けていてここには入りきらない。'
        report=gate.audit(rows)
        self.assertTrue(report['publication_held'])
        self.assertIn(3,report['first_flagged_cue_ids'])
        self.assertGreater(report['reasons'].get('long_screen_line',0),0)
        self.assertGreater(report['reasons'].get('possible_future_dialogue_leak',0),0)
        self.assertNotIn('ロジャー',str(report))

    def test_multiline_overcrowding_alone_blocks(self):
        rows=[{'cue_id':1,'timing':'x','start_ms':0,
               'end_ms':10000,'english':'A','japanese':'この字幕です。\nこれは二行目です。\n三行目は不要です。'}]
        result=gate.audit(rows)
        self.assertEqual(result['reasons']['too_many_lines'],1)
        self.assertTrue(result['publication_held'])

    def test_bad_s20_held_with_all_cue_checkpoints_preserved(self):
        translation=good(20)
        translation['4']='悪いほど長い文章を何度も繰り返して視聴者が読めない字幕です。'*4
        store=self.setup_store(translation)
        try:
            original=service.publish_job
            def run(s,_base,_root,_args):
                item=s.jobs()[0]
                main.publish_ready(s,item,True)
            with self.clean_patch():
                result=daily_worker.run_one(
                    self.state,self.jid,base=self.root,worker=run)
            self.assertEqual(result,'publish_hold')
            self.assertIs(service.publish_job,original)
            self.assertEqual(len([r for r in store.rows(self.jid) if r['japanese']]),20)
            self.assertEqual(next(j for j in store.jobs() if j['id']==self.jid)['status'],
                             'publish_hold')
            self.assertFalse(list(self.media.glob('*.ja.srt')))
        finally:
            store.cn.close()

    def test_verified_s20_is_create_only_and_database_published(self):
        store=self.setup_store()
        try:
            original=service.publish_job
            def run(s,_base,_root,_args):
                main.publish_ready(s,s.jobs()[0],True)
            with self.clean_patch():
                outcome=daily_worker.run_one(
                    self.state,self.jid,base=self.root,worker=run)
            self.assertEqual(outcome,'published')
            self.assertIs(service.publish_job,original)
            result=self.video.with_name(self.video.stem+'.Bruiser Japanese.ja.srt')
            self.assertTrue(result.is_file())
            self.assertEqual(len(service.parse_srt(result.read_bytes())),20)
            self.assertEqual(result.stat().st_mode&0o777,0o644)
            self.assertEqual(next(j for j in store.jobs() if j['id']==self.jid)['status'],
                             'published')
            self.assertEqual(self.video.read_bytes(),b'example video')
            self.assertFalse(list(self.media.glob('*.staging-*.tmp')))
        finally:
            store.cn.close()

    def test_interruption_during_write_does_not_leave_partial_final_srt(self):
        store=self.setup_store()
        try:
            job=store.jobs()[0]
            with self.clean_patch(),patch.object(
                gate.os,'link',side_effect=OSError('simulated interruption')):
                with self.assertRaisesRegex(OSError,'simulated interruption'):
                    gate.publish_atomically(store,job,service.publish_job,
                                            service,True)
            target=self.video.with_name(self.video.stem+'.Bruiser Japanese.ja.srt')
            self.assertFalse(target.exists())
            self.assertEqual(next(j for j in store.jobs() if j['id']==self.jid)['status'],
                             'translated')
            with self.clean_patch():
                dest,state=gate.publish_atomically(store,job,service.publish_job,
                                                   service,True)
            self.assertEqual(state,'published')
            self.assertTrue(dest.is_file())
        finally:store.cn.close()

    def test_power_cut_after_fully_linked_file_can_resume_without_overwrite(self):
        store=self.setup_store()
        try:
            job=store.jobs()[0]
            with self.clean_patch(),patch.object(
                service,'stamp',side_effect=RuntimeError('simulate power cut')):
                with self.assertRaisesRegex(RuntimeError,'simulate power cut'):
                    gate.publish_atomically(store,job,service.publish_job,
                                            service,True)
            target=self.video.with_name(self.video.stem+'.Bruiser Japanese.ja.srt')
            original=target.read_bytes()
            self.assertEqual(len(service.parse_srt(original)),20)
            self.assertEqual(next(j for j in store.jobs() if j['id']==self.jid)['status'],
                             'translated')
            with self.clean_patch():
                gate.publish_atomically(store,job,service.publish_job,
                                        service,True)
            self.assertEqual(target.read_bytes(),original)
            self.assertEqual(next(j for j in store.jobs() if j['id']==self.jid)['status'],
                             'published')
        finally:store.cn.close()

    def test_preserves_older_ja_tracks(self):
        store=self.setup_store()
        try:
            prior=self.video.with_name(self.video.stem+'.Bruiser Pilot Japanese.ja.srt')
            prior.write_bytes(b'old pilot track')
            with self.clean_patch():
                with self.assertRaisesRegex(RuntimeError,'Existing Japanese'):
                    gate.publish_atomically(store,store.jobs()[0],
                                            service.publish_job,service,True)
            self.assertEqual(prior.read_bytes(),b'old pilot track')
            self.assertFalse(self.video.with_name(
                self.video.stem+'.Bruiser Japanese.ja.srt').exists())
        finally:store.cn.close()

    def test_new_worker_qa_does_not_affect_other_titles(self):
        self.assertFalse(gate.is_american_dad('/movies/Primate.2026.mkv'))
        self.assertTrue(gate.is_american_dad('/television/American.Dad.S20E01.mkv'))


if __name__=='__main__':
    unittest.main()
