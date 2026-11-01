"""Offline integration and failure-injection tests. No Ollama, Docker or real media."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import service as s
import main as cli


def sample(n=24):
    return ('\n\n'.join(f'{i}\n00:00:{(i//60)%60:02d},{i%60:03d} --> 00:00:{(i//60)%60:02d},{(i%60)+100:03d}\nOriginal English cue {i}' for i in range(1,n+1))+'\n').encode()


def fixture(n=24,prior=None):
    d=tempfile.TemporaryDirectory()
    root=Path(d.name)
    st=s.Store(root)
    st.add('horror-film',root/'movie.mkv',sample(n),'eng',prior=prior or {})
    job=st.jobs()[0]
    return d,st,job


class SubHubTests(unittest.TestCase):
    def test_srt_roundtrip(self):
        rows=s.parse_srt(sample(3))
        ja={str(r[0]):'こんにちは' for r in rows}
        rendered=s.render_srt(rows,ja)
        again=s.parse_srt(rendered)
        self.assertEqual(len(again),3)
        self.assertEqual([r[1] for r in rows],[r[1] for r in again])
    def test_empty_numbered_cue(self):
        data=b'1\n00:00:01,000 --> 00:00:01,500\n\n2\n00:00:02,000 --> 00:00:02,500\nHi!\n'
        rows=s.parse_srt(data)
        self.assertEqual([r[0] for r in rows],[2])
    def test_duplicate_source_cue_rejected(self):
        with self.assertRaises(ValueError):s.parse_srt(sample(2)+sample(2))
    def test_bad_timing_rejected(self):
        with self.assertRaises(ValueError):s.parse_srt(b'1\n00:00:03,000 --> 00:00:01,000\nHello\n')
    def test_partial_resume_import(self):
        d,st,j=fixture(264,{str(i):'こんにちは' for i in range(1,253)})
        try:self.assertEqual(st.jobs()[0]['ja'],252)
        finally:st.cn.close();d.cleanup()
    def test_failing_batch_isolated_and_other_cues_complete(self):
        prior={str(i):'こんにちは' for i in range(1,253)}
        d,st,job=fixture(264,prior)
        seen=[]
        def fail_256(base,part,memory):
            ids=[r['cue_id'] for r in part];seen.append(ids)
            if 256 in ids and len(ids)>1:raise ValueError('Unusable Japanese for cue 256')
            return {str(i):'こんにちは' for i in ids}
        try:
            total=s.translate_window(st,Path(d.name),job,st.rows(job['id'])[252:],call=fail_256)
            self.assertEqual(total,12)
            self.assertEqual(st.jobs()[0]['ja'],264)
            self.assertEqual(st.jobs()[0]['held'],0)
            self.assertTrue(any(len(x)==1 and x==[256] for x in seen))
        finally:st.cn.close();d.cleanup()
    def test_irrecoverable_one_cue_does_not_block_other_cues(self):
        d,st,j=fixture(12)
        try:
            def invalid(base,part,memory):
                return {str(r['cue_id']):('---' if r['cue_id']==7 else 'こんにちは') for r in part}
            # multiple requests in one test make cue 7 exhaust its bounded budget
            for n in range(5):s.translate_window(st,Path(d.name),j,st.rows(j['id']),call=invalid)
            job=st.jobs()[0]
            self.assertEqual(job['ja'],11)
            self.assertEqual(job['held'],1)
            self.assertEqual(st.rows(j['id'])[6]['failed'],5)
        finally:st.cn.close();d.cleanup()
    def test_valid_cues_survive_failed_batch(self):
        d,st,j=fixture(12)
        try:
            first=[True]
            def partial(base,part,memory):
                if first[0]:first[0]=False;return {'1':'こんにちは','2':'こんにちは'}
                return {str(r['cue_id']):'こんにちは' for r in part}
            s.translate_window(st,Path(d.name),j,st.rows(j['id']),call=partial)
            self.assertEqual(st.jobs()[0]['ja'],12)
        finally:st.cn.close();d.cleanup()
    def test_no_double_import(self):
        d,st,j=fixture(3)
        try:
            self.assertFalse(st.add(j['id'],j['video'],sample(3),'eng'))
            self.assertEqual(len(st.jobs()),1)
        finally:st.cn.close();d.cleanup()
    def test_source_changed_refused(self):
        d,st,j=fixture(3)
        try:
            with self.assertRaises(RuntimeError):st.add(j['id'],j['video'],sample(4),'eng')
        finally:st.cn.close();d.cleanup()
    def test_publish_requires_full_translation(self):
        d,st,j=fixture(3)
        try:
            with patch.object(s,'secure_video'), patch.object(s,'audio_language',return_value='eng'):
                with self.assertRaises(RuntimeError):s.publish_job(st,j,apply=False)
        finally:st.cn.close();d.cleanup()
    def test_publish_create_only_and_japanese_only(self):
        d,st,j=fixture(3)
        try:
            vid=Path(j['video']);vid.write_bytes(b'movie')
            st.record_japanese(j['id'],{str(i):'こんにちは' for i in range(1,4)})
            with patch.object(s,'secure_video'), patch.object(s,'audio_language',return_value='eng'):
                dst,state=s.publish_job(st,j,apply=True)
                self.assertEqual(state,'published')
                self.assertTrue(dst.exists())
                self.assertEqual(len(s.parse_srt(dst.read_bytes())),3)
                self.assertFalse(dst.with_name(vid.stem+'.Bruiser Bilingual.en.srt').exists())
        finally:st.cn.close();d.cleanup()
    def test_preexisting_editorial_rejects_machine_overwrite(self):
        d,st,j=fixture(3)
        try:
            vid=Path(j['video']);vid.write_bytes(b'movie')
            existing=vid.with_name(vid.stem+'.Bruiser Japanese.ja.srt');existing.write_text('approved human translation')
            st.record_japanese(j['id'],{str(i):'こんにちは' for i in range(1,4)})
            with patch.object(s,'secure_video'), patch.object(s,'audio_language',return_value='eng'):
                with self.assertRaises(RuntimeError):s.publish_job(st,j,apply=True)
            self.assertEqual(existing.read_text(),'approved human translation')
        finally:st.cn.close();d.cleanup()
    def test_memory_scope_and_approved_only(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);p=base/'subhub-household/approved-memory.jsonl';p.parent.mkdir(parents=True)
            p.write_text('\n'.join(json.dumps(x) for x in [
              {'approved':True,'scope':'horror','english':'I saw someone here','japanese':'誰か見た'},
              {'approved':False,'scope':'horror','english':'I saw someone here','japanese':'禁止'},
              {'approved':True,'scope':'american-dad','english':'I saw someone here','japanese':'別'}]))
            got=s.recall_memory(base,'horror',[{'english':'I saw someone here'}])
            self.assertIn('誰か見た',got);self.assertNotIn('禁止',got);self.assertNotIn('別',got)
    def test_targeted_hy_sample(self):
        d,st,j=fixture(110)
        try:
            rows=st.rows(j['id']);ids=s.risk_hy_ids(rows,32)
            self.assertEqual(len(ids),32);self.assertEqual(len(set(ids)),32)
        finally:st.cn.close();d.cleanup()
    def test_hy_does_not_block_publish(self):
        d,st,j=fixture(3)
        try:
            st.record_japanese(j['id'],{str(i):'こんにちは' for i in range(1,4)})
            with patch.object(s,'secure_video'), patch.object(s,'audio_language',return_value='eng'):
                target,status=s.publish_job(st,j,apply=False)
                self.assertEqual(status,'dry-run')
        finally:st.cn.close();d.cleanup()
    def test_dashboard_readonly(self):
        d,st,j=fixture(4)
        try:
            st.cn.close()
            dashboard=cli.dashboard(Path(d.name)).decode()
            self.assertIn('horror-film',dashboard)
            self.assertIn('0/4',dashboard)
        finally:d.cleanup()
    def test_frozen_legacy_queue_not_modified(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);b=base/'subhub-household';b.mkdir()
            data={'jobs':[{'id':'horror-test','enabled':True,'learning_scope':'horror','host_video_path':'/not-existing','source':'/media/xx','container':'sublarr-pilot'}]}
            payload=json.dumps(data);(b/'jobs.json').write_text(payload)
            st=s.Store(base/'new')
            try:
                s.import_legacy(st,base,1,['horror'])
                self.assertEqual((b/'jobs.json').read_text(),payload)
                self.assertEqual(len(st.jobs()),0)
            finally:st.cn.close()

if __name__=='__main__':unittest.main(verbosity=2)

class CampaignIntegrationTests(unittest.TestCase):
    def test_two_titles_one_irrecoverable_cue_other_title_publishes(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);base=root/'legacy';base.mkdir()
            st=s.Store(root/'new');v1=root/'first.mkv';v2=root/'second.mkv'
            v1.write_bytes(b'movie 1');v2.write_bytes(b'movie 2')
            st.add('film-one',v1,sample(12),'eng',priority=1)
            st.add('film-two',v2,sample(12),'eng',priority=2)
            def translation(base,part,memory):
                return {str(r['cue_id']):('????' if r['cue_id']==7 and part[0]['cue_id']==1 else 'こんにちは') for r in part}
            class DummyMeter:
                def __init__(self,*args,**kwargs):self.wh=0.0
                def start(self):pass
                def finish(self):return {'seconds':0}
            a=Namespace(max_minutes=5,max_titles=10,hy_sample=0,sample_seconds=15,
                        mode='translate',max_gpu_c=90,max_cpu_c=90,publish=True,skip_hy=True)
            try:
                with patch.object(s,'OLD_WORKER_LOCK',root/'old.lock'),patch.object(s,'secure_video'),patch.object(s,'audio_language',return_value='eng'),patch.object(cli,'Meter',DummyMeter),patch.object(cli,'thermal_guard'):
                    done=cli.run(st,base,root/'new',a,translator=translation)
                self.assertEqual(done,2)
                self.assertTrue(v1.with_name(v1.stem+'.Bruiser Japanese.ja.srt').is_file())
                self.assertTrue(v2.with_name(v2.stem+'.Bruiser Japanese.ja.srt').is_file())
                self.assertEqual({x['status'] for x in st.jobs()},{'published'})
            finally:st.cn.close()

    def test_if_one_cue_never_recovers_second_film_still_publishes(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);base=root/'legacy';base.mkdir()
            st=s.Store(root/'new');v1=root/'first.mkv';v2=root/'second.mkv'
            v1.write_bytes(b'movie 1');v2.write_bytes(b'movie 2')
            st.add('film-one',v1,sample(12),'eng',priority=1)
            st.add('film-two',v2,sample(12).replace(b'Original English cue 7',b'Safe dialogue 7'),'eng',priority=2)
            def translation(base,part,memory):
                return {str(r['cue_id']):('???' if r['cue_id']==7 and r['english'].startswith('Original') else 'こんにちは') for r in part}
            class DummyMeter:
                def __init__(self,*args,**kwargs):self.wh=0.0
                def start(self):pass
                def finish(self):return {}
            a=Namespace(max_minutes=5,max_titles=10,hy_sample=0,sample_seconds=15,
                        mode='translate',max_gpu_c=90,max_cpu_c=90,publish=True,skip_hy=True)
            try:
                with patch.object(s,'OLD_WORKER_LOCK',root/'old.lock'),patch.object(s,'secure_video'),patch.object(s,'audio_language',return_value='eng'),patch.object(cli,'Meter',DummyMeter),patch.object(cli,'thermal_guard'):
                    done=cli.run(st,base,root/'new',a,translator=translation)
                self.assertEqual(done,1)
                self.assertEqual(st.cn.execute("SELECT status FROM jobs WHERE id='film-one'").fetchone()[0],'needs_review')
                self.assertEqual(st.cn.execute("SELECT status FROM jobs WHERE id='film-two'").fetchone()[0],'published')
                self.assertFalse(v1.with_name(v1.stem+'.Bruiser Japanese.ja.srt').exists())
            finally:st.cn.close()
