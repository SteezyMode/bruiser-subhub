"""Offline nightly ASR-maintenance tests, zero real Whisper/host IO."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import american_dad_maintenance as m


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        self.media=self.dir/'media'
        self.media.mkdir()
        self.state=self.dir/'subhub-state'
        self.videos=[]
        self.em={}
        for season in (8,20):
            for ep in range(1,13):
                video=self.media/('American.Dad.S%02dE%02d.mkv'%(season,ep))
                video.write_bytes(b'placeholder')
                self.videos.append(video)
                self.em[video]={
                    'ja':False,'audio_en':True,
                    'embedded_en':3 if season==20 else None}
        self.logs=[]
        self.launches=[]
        self.asr=[]
    def probe(self,video):
        return dict(self.em[video])
    def videos_iter(self,roots):
        return self.videos
    def fake_asr(self,video):
        self.asr.append(video)
        self.em[video]['embedded_en']=3
        return True
    def launcher(self,root,seasons,maxepisodes,minutes):
        self.launches.append((root,seasons,maxepisodes,minutes))
        return {'pid':7,'log':'safe'}
    def once(self,asr=None):
        with patch.object(m.intake.service,'secure_video'):
            return m.run_once((self.media,),self.state,now=2_000_000_000,
                iter_videos=self.videos_iter,probe_fn=self.probe,
                asr_run=asr or self.fake_asr,launch=self.launcher,
                log=lambda *x:self.logs.append(x))

    def test_choose_source_rich_season_then_one_missing_english(self):
        self.em[next(x for x in self.videos if 'S20E12' in x.name)]['embedded_en']=None
        result=self.once()
        self.assertEqual(result,'started')
        self.assertEqual(len(self.asr),1)
        self.assertEqual(self.launches[0][1],(20,))
        self.assertEqual(m.auto.current(self.state),20)
        self.assertTrue(any(x[0]=='ASR_SOURCE_READY' and 'S20E12' in x[1]
                            for x in self.logs))

    def test_no_subtitles_at_all_uses_s08_fallback_and_transcribes_one(self):
        for video in self.videos:
            self.em[video]['embedded_en']=None
        self.assertEqual(self.once(),'started')
        self.assertEqual(m.auto.current(self.state),8)
        self.assertIn('S08E01',self.asr[0].name)
        self.assertEqual(self.launches[0][1],(8,))

    def test_failed_first_asr_is_deferred_and_not_retried(self):
        for video in self.videos:
            self.em[video]['embedded_en']=None
        self.assertEqual(self.once(asr=lambda video:(
            self.asr.append(video) or False)),'no_english')
        self.assertEqual(len(self.asr),1)
        self.assertEqual(self.launches,[])
        self.assertEqual(self.once(asr=lambda video:(
            self.asr.append(video) or False)),'no_english')
        self.assertEqual(len(self.asr),2)
        self.assertNotEqual(self.asr[0],self.asr[1])
        self.assertEqual(m.failures(self.state)[
            __import__('hashlib').sha256(
                str(self.asr[0].resolve()).encode()).hexdigest()],
            2_000_000_000+m.ASR_COOLDOWN)

    def test_pause_prevents_model_and_campaign(self):
        self.state.mkdir()
        (self.state/'PAUSE').touch()
        self.assertEqual(self.once(),'paused')
        self.assertEqual(self.asr,[])
        self.assertEqual(self.launches,[])

    def test_no_episode_candidates_does_not_claim_success(self):
        for video in self.videos:
            video.unlink()
        self.videos.clear()
        self.assertEqual(self.once(),'no_season')
        self.assertEqual(self.asr,[])
        self.assertEqual(self.launches,[])

    def test_selection_sticky_on_second_run(self):
        self.once()
        self.assertEqual(m.auto.current(self.state),20)
        self.em.update({v:{'ja':False,'audio_en':True,'embedded_en':3}
                        for v in self.videos if 'S08' in v.name})
        self.launches.clear()
        self.assertEqual(self.once(),'started')
        self.assertEqual(self.launches[0][1],(20,))

    def test_existing_japanese_is_not_transcribed(self):
        for video in self.videos:
            self.em[video]['embedded_en']=None
        ja=next(v for v in self.videos if 'S08E01' in v.name)
        (ja.parent/(ja.stem+'.ja.srt')).write_text('existing')
        self.once()
        self.assertNotIn(ja,self.asr)
        self.assertIn('S08E02',self.asr[0].name)

    def test_no_missing_source_skips_asr_and_launches_translation(self):
        self.assertEqual(self.once(),'started')
        self.assertEqual(self.asr,[])
        self.assertEqual(len(self.launches),1)


if __name__=='__main__':
    unittest.main()
