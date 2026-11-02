"""Offline tests for one-title household Japanese subtitle intake.

Never invoke ffmpeg, ffprobe, Ollama or a real installed SubHub worker.
"""
import fcntl
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import service
from tools import daily_japanese as day


def srt(n=30,english='Some ordinary English dialogue.'):
    out=[]
    for i in range(n):
        start=i*3
        begin='%02d:%02d:%02d,000'%(start//3600,(start//60)%60,start%60)
        end=start+2
        finish='%02d:%02d:%02d,000'%(end//3600,(end//60)%60,end%60)
        out.append('%d\n%s --> %s\n%s'%(i+1,begin,finish,english))
    return ('\n\n'.join(out)+'\n').encode('utf8')


class DailyIntakeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp=Path(tmp.name)
        self.media=self.tmp/'Library'
        self.media.mkdir()
        self.root=self.tmp/'state'
        self.old_lock=self.tmp/'legacy.lock'
        self.v1=self.movie('A Movie')
        self.v2=self.movie('B Movie')
        self.meta={'audio_en':True,'ja':False,'embedded_en':3}
        self.probed=[]
        self.extracted=[]

    def movie(self,stem):
        path=self.media/(stem+'.mkv')
        path.write_bytes(b'test video content')
        return path

    def probe(self,vid):
        self.probed.append(vid)
        return dict(self.meta)

    def source(self,vid,meta):
        self.extracted.append((vid,meta))
        return srt(),30,'embedded_english_text'

    def daily(self,**kwargs):
        with patch.object(service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
             service,'SOURCE_ROOTS',(self.media,)):
            return day.daily((self.media,),self.root,
                             probe_fn=self.probe,source_fn=self.source,
                             **kwargs)

    def test_read_only_preview_never_creates_queue_cursor_or_media_tracks(self):
        before={str(p):p.read_bytes() for p in self.media.iterdir()}
        self.assertEqual(self.daily(),'preview')
        self.assertEqual(self.probed,[self.v1])
        self.assertFalse(self.root.exists())
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.media.iterdir()})
        self.assertEqual(list(self.media.glob('*.ja.srt')),[])

    def test_one_title_queued_and_next_run_rotates_to_next(self):
        with patch.object(service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
             service,'SOURCE_ROOTS',(self.media,)):
            self.assertEqual(day.daily((self.media,),self.root,apply=True,
                probe_fn=self.probe,source_fn=self.source),'queued')
            store=service.Store(self.root)
            try:
                jobs=store.jobs()
                self.assertEqual(len(jobs),1)
                self.assertEqual(jobs[0]['video'],str(self.v1))
                self.assertEqual(jobs[0]['n'],30)
                self.assertEqual(jobs[0]['status'],'queued')
                self.assertTrue((self.root/'sources'/
                                 (jobs[0]['id']+'.en.srt')).is_file())
            finally:
                store.cn.close()
            self.assertEqual(day.daily((self.media,),self.root,apply=True,
                probe_fn=self.probe,source_fn=self.source),'queued')
            store=service.Store(self.root)
            try:
                self.assertEqual(len(store.jobs()),2)
                self.assertEqual({x['video'] for x in store.jobs()},
                                 {str(self.v1),str(self.v2)})
            finally:
                store.cn.close()
            self.assertEqual(day.daily((self.media,),self.root,apply=True,
                probe_fn=self.probe,source_fn=self.source),'no_ready')
        self.assertEqual(list(self.media.glob('*.ja.srt')),[])

    def test_existing_japanese_srt_ass_vtt_and_embedded_block_intake(self):
        vid=self.v1
        for suffix in ('.ja.srt','.Japanese.ass','.editorial.vtt','.jp.srt'):
            p=vid.with_name(vid.stem+suffix)
            p.write_bytes(b'editorial Japanese subtitle')
            try:
                self.assertTrue(day.already_ja(vid))
                self.assertEqual(self.daily(probes=1),'preview' if
                    self.v2.is_file() else 'no_ready')
                self.assertEqual(self.probed[-1],self.v2)
            finally:p.unlink()
        self.probed.clear()
        self.meta['ja']=True
        self.assertEqual(self.daily(probes=2),'no_ready')
        self.assertEqual(self.extracted,[])

    def test_japanese_sidecar_on_different_movie_not_misclassified(self):
        foreign=self.media/'A Movie Extended.ja.srt'
        foreign.write_bytes(b'Japanese for another film')
        self.assertFalse(day.already_ja(self.v1))
        self.assertEqual(self.daily(),'preview')
        self.assertEqual(self.probed,[self.v1])

    def test_only_verified_english_primary_audio_is_queued(self):
        self.meta['audio_en']=False
        self.assertEqual(self.daily(probes=2),'no_ready')
        self.assertEqual(self.extracted,[])
        self.assertFalse(self.root.exists())

    def test_probe_and_embedded_extraction_parameters_and_sidecar_priority(self):
        en=self.v1.with_name(self.v1.stem+'.en.srt')
        en.write_bytes(srt())
        cmd=[]
        def runner(args,**kwargs):
            cmd.append(args)
            if args[0]=='ffprobe':
                result={'streams':[
                    {'index':0,'codec_type':'audio',
                     'tags':{'language':'eng'},'disposition':{'default':1}},
                    {'index':1,'codec_type':'subtitle','codec_name':'hdmv_pgs_subtitle',
                     'tags':{'language':'eng'},'disposition':{'default':0}},
                    {'index':2,'codec_type':'subtitle','codec_name':'subrip',
                     'tags':{'language':'eng'},'disposition':{'default':1}},
                    {'index':3,'codec_type':'subtitle','codec_name':'subrip',
                     'tags':{'language':'jpn'},'disposition':{}}]}
                return SimpleNamespace(returncode=0,stdout=json.dumps(result).encode())
            return SimpleNamespace(returncode=0,stdout=srt())
        info=day.probe(self.v1,runner)
        self.assertTrue(info['ja'])
        self.assertEqual(info['embedded_en'],2)
        self.assertEqual(day.source(self.v1,info,runner)[2],'named_english_srt')
        self.assertEqual(len(cmd),1)
        en.unlink()
        self.assertEqual(day.source(self.v1,info,runner)[2],'embedded_english_text')
        self.assertIn('-map',cmd[-1])
        self.assertEqual(cmd[-1][cmd[-1].index('-map')+1],'0:2')
        self.assertEqual(cmd[-1][-1],'pipe:1')

    def test_incomplete_sparse_or_wrong_language_sources_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError,'Sparse English SRT'):
            raw=(b'1\n00:00:01,000 --> 00:00:02,000\nHi.\n\n'
                 b'2\n00:00:02,000 --> 00:00:03,000\n\n'
                 b'3\n00:00:03,000 --> 00:00:04,000\nBye.\n')
            src=self.v1.with_name(self.v1.stem+'.english.srt')
            src.write_bytes(raw)
            day.source(self.v1,self.meta)
        src.unlink()
        invalid=self.v1.with_name(self.v1.stem+'.unknown.srt')
        invalid.write_bytes(srt())
        self.assertIsNone(day.english_srt(self.v1))

    def test_lock_prevents_queueing_while_worker_is_active(self):
        with patch.object(service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
             service,'SOURCE_ROOTS',(self.media,)):
            with day.exclusive_intake(self.root):
                with self.assertRaisesRegex(RuntimeError,'worker already active'):
                    day.queue_one(day.next_ready(
                        (self.media,),self.root,probe_fn=self.probe,
                        source_fn=self.source)[0],(self.media,),self.root,
                        self.probe)
        self.assertFalse((self.root/'jobs.sqlite3').exists())

    def test_recheck_existing_japanese_after_scan_before_queue_write(self):
        item,_,_=day.next_ready((self.media,),self.root,probe_fn=self.probe,
                                source_fn=self.source)
        new=self.v1.with_name(self.v1.stem+'.jpn.srt')
        new.write_bytes(b'new editorial JA')
        with self.assertRaisesRegex(RuntimeError,'Japanese subtitles appeared'):
            day.ensure_still_safe(item,(self.media,),self.probe)
        self.assertFalse((self.root/'jobs.sqlite3').exists())

    def test_worker_is_only_started_explicitly_after_successful_queue_add(self):
        calls=[]
        def start(command,**kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0,stdout='STARTED detached PID 123\n')
        worker=self.tmp/'installed_main.py'
        worker.write_bytes(b'print("no execution in test")')
        with patch.object(day,'HOST_CODE',self.tmp),patch.object(
             service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
             service,'SOURCE_ROOTS',(self.media,)):
            self.assertEqual(day.daily((self.media,),self.root,apply=True,
                start=True,probes=4,probe_fn=self.probe,
                source_fn=self.source,worker=worker,runner=start),'started')
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][-2:],['--max-titles','1'])
        self.assertIn('--skip-hy',calls[0])
        self.assertIn('--publish',calls[0])
        self.assertEqual(list(self.media.glob('*.ja.srt')),[])

    def test_status_ro_only_and_deterministic_job_id(self):
        first=day.job_id(self.v1)
        self.assertEqual(first,day.job_id(self.v1))
        self.assertRegex(first,r'^daily-a-movie-[0-9a-f]{12}$')
        self.assertEqual(day.existing_jobs(self.root),set())
        with patch.object(service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
             service,'SOURCE_ROOTS',(self.media,)):
            self.assertEqual(day.daily((self.media,),self.root,apply=True,
                probe_fn=self.probe,source_fn=self.source),'queued')
        self.assertEqual(day.existing_jobs(self.root),{str(self.v1)})

    def test_reject_unsafe_media_root_and_symlinked_video(self):
        with self.assertRaisesRegex(RuntimeError,'missing or symlinked'):
            day.ensure_roots((self.tmp/'not-a-root',))
        link=self.media/'Linked.mkv'
        link.symlink_to(self.v1)
        self.assertNotIn(link,list(day.video_files((self.media,))))

    def test_start_requires_explicit_apply(self):
        with self.assertRaisesRegex(ValueError,'requires --apply'):
            self.daily(start=True)


if __name__=='__main__':
    unittest.main()
