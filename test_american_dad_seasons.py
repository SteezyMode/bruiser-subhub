"""No-Ollama tests for practical selectable American Dad season campaigns."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import tempfile
import unittest

import service
from tools import american_dad_seasons as season
from tools import daily_japanese as intake


def subtitle(n=35):
    def clock(k):
        return '%02d:%02d:%02d,000'%(k//3600,k//60%60,k%60)
    return ('\n\n'.join('%d\n%s --> %s\nWe should watch this show.'%(
        i+1,clock(i*3),clock(i*3+2)) for i in range(n))+'\n').encode('utf8')


class SeasonTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.media=self.base/'media'
        self.media.mkdir()
        self.root=self.base/'subhub1-state'
        self.old_lock=self.base/'old.lock'
        self.e801=self.make('American.Dad.S08E01')
        self.e802=self.make('American.Dad.S08E02')
        self.e803=self.make('American.Dad.S08E03')
        self.e901=self.make('American.Dad.S09E01')
        self.unrelated=self.make('Bottoms.2023')
        self.previous=self.make('American.Dad.S19E10')
        self.calls=[]

    def make(self,stem):
        p=self.media/(stem+'.mkv')
        p.write_bytes(b'fictional media')
        return p

    def probe(self,video):
        self.calls.append(('probe',video.name))
        return {'audio_en':True,'ja':False,'embedded_en':4}

    def source(self,video,info):
        self.calls.append(('source',video.name))
        return subtitle(),35,'embedded_english_text'

    def setup_queue(self):
        self.root.mkdir(exist_ok=True)
        db=service.Store(self.root)
        return db

    def translate(self,root,jid):
        self.calls.append(('translate',jid))
        st=service.Store(root)
        try:
            job=next(x for x in st.jobs() if x['id']==jid)
            self.assertIn('.S08E',job['video'])
            st.record_japanese(jid,{
                str(row['cue_id']):'自然な日本語です。'
                for row in st.rows(jid)})
            st.state(jid,'published')
        finally:
            st.cn.close()
        return 'published'

    def execute(self,seasons=(8,),**kwargs):
        with patch.object(service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
            service,'SOURCE_ROOTS',(self.media,)):
            return season.execute(
                (self.media,),self.root,seasons,
                probe_fn=self.probe,source_fn=self.source,
                translate=self.translate,**kwargs)

    def test_default_season_8_and_opt_in_season_9_only(self):
        found=season.discover((self.media,),(8,))
        self.assertEqual(list(found),[(8,1),(8,2),(8,3)])
        pair=season.discover((self.media,),(8,9))
        self.assertEqual(list(pair),[(8,1),(8,2),(8,3),(9,1)])
        self.assertNotIn((19,10),pair)
        self.assertEqual(season.validate_seasons([8]),(8,))
        with self.assertRaises(ValueError):
            season.validate_seasons([8,8])
        with self.assertRaises(ValueError):
            season.validate_seasons([8,9,10])

    def test_series_filter_cannot_select_unrelated_titles(self):
        noisy=self.make('Some.Other.S08E01')
        found=season.discover((self.media,),(8,))
        self.assertNotIn(noisy,found.get((8,1),[]))
        self.assertNotIn(self.unrelated,sum(found.values(),[]))

    def test_read_only_plan_no_queue_or_media_mutations(self):
        initial={str(p):p.read_bytes() for p in self.media.iterdir()}
        lines=[]
        result=season.plan((self.media,),self.root,(8,),
                           probe_fn=self.probe,
                           print_fn=lambda *x:lines.append(x))
        self.assertEqual(result['eligible'],3)
        self.assertFalse(self.root.exists())
        self.assertEqual(initial,{
            str(p):p.read_bytes() for p in self.media.iterdir()})
        self.assertTrue(any(x[0]=='SEASON_PLAN_SUMMARY' for x in lines))

    def test_three_episode_batch_uses_only_s8_and_existing_queue(self):
        result=self.execute()
        self.assertEqual(result['episode_attempts'],3)
        self.assertEqual(result['outcomes'],{'published':3})
        store=service.Store(self.root)
        try:
            jobs=store.jobs()
            self.assertEqual(len(jobs),3)
            self.assertTrue(all('.S08E' in j['video'] for j in jobs))
            self.assertTrue(all(j['status']=='published' for j in jobs))
            self.assertTrue(all(j['ja']==35 for j in jobs))
        finally:
            store.cn.close()
        self.assertEqual(len([x for x in self.calls if x[0]=='translate']),3)
        # Re-run after translation; queued source and translations protected.
        self.calls.clear()
        result=self.execute()
        self.assertEqual(result['episode_attempts'],0)
        self.assertEqual(result['outcomes'],{'published':3})
        self.assertFalse([x for x in self.calls if x[0]=='translate'])
        self.assertEqual(list(self.media.glob('*.ja.srt')),[])

    def test_skip_preexisting_ja_without_model_and_continue(self):
        existing=self.e801.with_name(self.e801.stem+'.ja.srt')
        existing.write_bytes(b'Existing editorial JA')
        with patch.object(service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
             service,'SOURCE_ROOTS',(self.media,)):
            result=self.execute()
        self.assertEqual(result['outcomes']['already_japanese'],1)
        self.assertEqual(result['outcomes']['published'],2)
        self.assertEqual(existing.read_bytes(),b'Existing editorial JA')
        store=service.Store(self.root)
        try:
            self.assertFalse(any('S08E01' in j['video'] for j in store.jobs()))
        finally:
            store.cn.close()

    def test_existing_embedded_ja_skipped(self):
        def local_probe(video):
            val=self.probe(video)
            if video==self.e802:
                val['ja']=True
            return val
        with patch.object(service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
            service,'SOURCE_ROOTS',(self.media,)):
            result=season.execute(
                (self.media,),self.root,(8,),probe_fn=local_probe,
                source_fn=self.source,translate=self.translate)
        self.assertEqual(result['outcomes']['already_japanese'],1)
        self.assertEqual(result['outcomes']['published'],2)
        self.assertFalse(any(x[0]=='source' and 'S08E02' in x[1]
                             for x in self.calls))

    def test_unavailable_english_skipped_without_stopping_other_episodes(self):
        def no_text(video):
            info=self.probe(video)
            if video==self.e802:
                info['embedded_en']=None
            return info
        with patch.object(service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
            service,'SOURCE_ROOTS',(self.media,)):
            result=season.execute((self.media,),self.root,(8,),
                probe_fn=no_text,source_fn=self.source,
                translate=self.translate)
        self.assertEqual(result['outcomes']['needs_english_or_review'],1)
        self.assertEqual(result['outcomes']['published'],2)

    def test_one_episode_bounded_and_can_resume_next_run(self):
        first=self.execute(max_episodes=1)
        self.assertEqual(first['episode_attempts'],1)
        self.assertEqual(first['outcomes']['published'],1)
        second=self.execute(max_episodes=1)
        self.assertEqual(second['episode_attempts'],1)
        self.assertEqual(second['outcomes']['published'],2)
        last=self.execute(max_episodes=2)
        self.assertEqual(last['episode_attempts'],1)
        self.assertEqual(last['outcomes']['published'],3)

    def test_pending_episode_resumes_existing_cue_checkpoints(self):
        db=self.setup_queue()
        try:
            db.add(intake.job_id(self.e801),self.e801,subtitle(),'eng',
                   scope='daily',priority=-20,
                   prior={str(i):'この字幕は完了' for i in range(1,13)})
        finally:
            db.cn.close()
        before_count=len([x for x in self.calls if x[0]=='source'])
        result=self.execute(max_episodes=1)
        self.assertEqual(result['outcomes']['published'],1)
        self.assertEqual(before_count,
                         len([x for x in self.calls if x[0]=='source']))
        db=service.Store(self.root)
        try:
            rows=db.rows(intake.job_id(self.e801))
            self.assertTrue(all(r['japanese'] for r in rows))
            self.assertEqual(rows[0]['japanese'],'この字幕は完了')
        finally:
            db.cn.close()

    def test_hold_does_not_loop_retranslate_blocked_episode(self):
        db=self.setup_queue()
        try:
            db.add(intake.job_id(self.e801),self.e801,subtitle(),'eng',
                   scope='daily')
            db.state(intake.job_id(self.e801),'needs_review')
        finally:
            db.cn.close()
        result=self.execute()
        self.assertEqual(result['outcomes']['needs_review'],1)
        self.assertEqual(result['outcomes']['published'],2)
        self.assertFalse(any(x[0]=='translate'
                         and 'S08E01' in x[1] for x in self.calls))

    def test_unknown_existing_legacy_job_not_modified(self):
        db=self.setup_queue()
        try:
            db.add('legacy-american-dad',self.e801,subtitle(),'eng')
        finally:
            db.cn.close()
        result=self.execute()
        self.assertEqual(result['outcomes']['existing_other_queue'],1)
        self.assertEqual(result['outcomes']['published'],2)

    def test_busy_campaign_lock_refuses_parallel_season_worker(self):
        with season.campaign_lock(self.root):
            with self.assertRaisesRegex(RuntimeError,'already active'):
                self.execute()
        self.assertFalse(list(self.media.glob('*.ja.srt')))

    def test_worker_failure_stops_campaign_no_extra_titles(self):
        seen=[]
        def fail(root,jid):
            seen.append(jid)
            raise RuntimeError('Worker was busy')
        with patch.object(service,'OLD_WORKER_LOCK',self.old_lock),patch.object(
            service,'SOURCE_ROOTS',(self.media,)):
            result=season.execute(
                (self.media,),self.root,(8,),
                probe_fn=self.probe,source_fn=self.source,
                translate=fail)
        self.assertEqual(result['outcomes']['interrupted'],1)
        self.assertEqual(len(seen),1)

    def test_pause_file_stops_before_any_episode(self):
        self.root.mkdir()
        (self.root/'PAUSE').write_bytes(b'paused\n')
        result=self.execute()
        self.assertEqual(result['episode_attempts'],0)
        self.assertIn('paused_or_out_of_time',result['outcomes'])

    def test_start_background_only_stages_detached_campaign(self):
        seen=[]
        def launcher(command,out):
            seen.append(command)
            return SimpleNamespace(pid=144)
        payload=season.start_background(
            self.root,(8,),15,360,
            script=self.base/'season_cmd.py',launcher=launcher)
        self.assertEqual(payload['pid'],144)
        self.assertTrue(Path(payload['log']).is_file())
        self.assertEqual(seen[0][seen[0].index('--seasons')+1],'8')
        self.assertNotIn('19',seen[0])
        self.assertFalse((self.root/'jobs.sqlite3').exists())


if __name__=='__main__':
    unittest.main()
