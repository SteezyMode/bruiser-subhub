"""Synthetic American Dad season selection; never touch models or host media."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import american_dad_autopilot as auto


class AutoSeasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.video_root=self.root/'videos'
        self.video_root.mkdir()
        self.state=self.root/'state'
        self.videos=[]
        self.english=set()
        self.logged=[]
        self.started=[]
        for season,n in ((8,18),(12,13),(19,12),(20,9)):
            for ep in range(1,n+1):
                path=self.video_root/'American Dad'/(
                    'American.Dad.S%02dE%02d.mkv'%(season,ep))
                path.parent.mkdir(exist_ok=True,parents=True)
                path.write_bytes(b'actual-video-placeholder')
                self.videos.append(path)
        self.english.update(v for v in self.videos
                            if 'S12' in v.name and int(v.name[-6:-4])<=9)
        self.english.update(v for v in self.videos
                            if 'S20' in v.name and int(v.name[-6:-4])<=8)

    def probe(self,video):
        return {'ja':False,'audio_en':True,
                'embedded_en':3 if video in self.english else None}

    def choices(self):
        return auto.coverage(
            (self.video_root,),self.state,
            iter_videos=lambda roots:self.videos,
            probe_fn=self.probe,log=lambda *x:self.logged.append(x))

    def launch(self,root,seasons,max_episodes,minutes):
        self.started.append((root,seasons,max_episodes,minutes))
        return {'pid':123,'log':'synthetic'}

    def run(self,start=False):
        return auto.autopilot(
            (self.video_root,),self.state,start=start,
            iter_videos=lambda roots:self.videos,probe_fn=self.probe,
            launcher=self.launch,log=lambda *x:self.logged.append(x))

    def test_choose_real_available_season_not_user_example_missing_s08(self):
        selected=self.run(start=True)
        self.assertIsNotNone(selected)
        self.assertEqual(selected['season'],20)
        self.assertEqual(selected['new'],8)
        self.assertEqual(selected['blocked'],1)
        self.assertEqual(self.started[0][1],(20,))
        self.assertEqual(self.started[0][2:],(50,480))
        saved=json.loads((self.state/auto.SELECTION).read_text())
        self.assertEqual(saved['season'],20)
        self.assertTrue(any(x[0]=='AUTO_SEASON_COVERAGE' for x in self.logged))

    def test_plan_never_writes_selection_or_launches(self):
        selected=self.run(start=False)
        self.assertEqual(selected['season'],20)
        self.assertFalse(self.started)
        self.assertFalse((self.state/auto.SELECTION).exists())

    def test_nothing_eligible_no_phantom_translation(self):
        self.english.clear()
        self.assertIsNone(self.run(start=True))
        self.assertFalse(self.started)
        self.assertFalse((self.state/auto.SELECTION).exists())
        self.assertTrue(any(x[0]=='AUTO_SEASON_NOT_STARTED' for x in self.logged))

    def test_existing_japanese_counts_as_watchable_not_new_work(self):
        self.english=set(v for v in self.videos if 'S12' in v.name)
        one=next(v for v in self.videos if 'S12' in v.name)
        (one.parent/(one.stem+'.ja.srt')).write_text('existing editorial')
        found=next(x for x in self.choices() if x['season']==12)
        self.assertEqual(found['already_japanese'],1)
        self.assertEqual(found['new'],12)
        self.assertEqual(found['blocked'],0)

    def test_do_not_select_partial_seasons_under_minimum_new_episodes(self):
        sample=[{'season':7,'total':17,'new':1,'resume':0,
                 'viewable_with_translation':16,'coverage_pct':94},
                {'season':8,'total':18,'new':2,'resume':0,
                 'viewable_with_translation':17,'coverage_pct':94}]
        self.assertIsNone(auto.rank(sample))

    def test_sticky_campaign_does_not_jump_between_seasons_during_progress(self):
        self.run(start=True) # season 20
        self.english.update(v for v in self.videos if 'S12' in v.name)
        self.started.clear()
        selected=self.run(start=True)
        self.assertEqual(selected['season'],20)
        self.assertEqual(self.started[0][1],(20,))
        self.assertTrue(any(x[0]=='AUTO_SEASON_SELECTED' and
                        '"resume_selected_season"' in x[1]
                        for x in self.logged))

    def test_finished_campaign_allows_new_season_selection(self):
        self.run(start=True)
        self.english=set(v for v in self.videos if 'S12' in v.name)
        self.started.clear()
        chosen=self.run(start=True)
        self.assertEqual(chosen['season'],12)
        self.assertEqual(self.started[0][1],(12,))

    def test_fuzzy_untagged_episodes_not_inferred(self):
        extra=self.video_root/'American Dad'/'Unknown episode.mkv'
        extra.write_bytes(b'video')
        self.videos.append(extra)
        self.assertEqual(len(auto.discover(
            (self.video_root,),iter_videos=lambda roots:self.videos)),52)

    def test_existing_job_does_not_get_duplicated_if_not_daily(self):
        with patch.object(auto.seasons,'queue_jobs',return_value={
          str(self.videos[0]):{'id':'old-legacy','status':'queued'}}):
            found=self.choices()
        eight=next(x for x in found if x['season']==8)
        self.assertEqual(eight['new'],0)
        self.assertEqual(eight['resume'],0)
        self.assertEqual(eight['blocked'],18)

    def test_ja_embedded_never_claimed_as_new_translation(self):
        sample=next(x for x in self.videos if 'S20' in x.name)
        def probe(video):
            info=self.probe(video)
            if video==sample:
                info['ja']=True
            return info
        with patch.object(auto.intake,'probe',side_effect=probe):
            results=auto.coverage(
                (self.video_root,),self.state,
                iter_videos=lambda roots:self.videos,
                probe_fn=probe,log=lambda *x:None)
        season20=next(x for x in results if x['season']==20)
        self.assertEqual(season20['already_japanese'],1)
        self.assertEqual(season20['new'],7)


if __name__=='__main__':
    unittest.main()
