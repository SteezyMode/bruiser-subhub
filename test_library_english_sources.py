"""Offline library-wide English inventory and exact-hash subtitle downloader."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import library_english_sources as lib
from tools import jellyfin_english_sources as jf


def srt(n=24):
    def tm(k):
        return f'{k//3600:02}:{k//60%60:02}:{k%60:02},000'
    return ('\n\n'.join(
        f'{i+1}\n{tm(i*3)} --> {tm(i*3+2)}\nSome English dialogue.'
        for i in range(n))+'\n').encode('utf8')


def item(file,type_='Episode', season=None, episode=None,subs=None):
    return {'Type':type_,'Id':('id'+str(abs(hash(str(file))))[:12]),
            'Path':str(file),'Name':file.stem,'SeriesName':'American Dad',
            'ParentIndexNumber':season,'IndexNumber':episode,
            'MediaStreams':[
                {'Type':'Audio','Language':'eng','IsDefault':True},
                *[{'Type':'Subtitle','Language':lang,
                   'Codec':codec,'IsForced':False}
                  for lang,codec in (subs or [])]]}


class Client:
    def __init__(self,items):
        self.items=items
        self.queries=[]
        self.downloads=[]
        self.results={}
        self.write=True
        self.failure=None

    def get(self,path):
        self.queries.append(path)
        if path.startswith('/Items?'):
            return {'Items':self.items,'TotalRecordCount':len(self.items)}
        if path.endswith('/RemoteSearch/Subtitles/eng'):
            if self.failure:
                raise self.failure
            ident=path.split('/')[2]
            return self.results.get(ident,[])
        raise AssertionError('Unexpected Jellyfin GET '+path)

    def post(self,path,data=None):
        self.downloads.append(path)
        parts=path.split('/')
        ident=parts[2]
        if self.write:
            match=next(x for x in self.items if x['Id']==ident)
            video=Path(match['Path'])
            (video.parent/(video.stem+'.en.srt')).write_bytes(srt())


class LibraryInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        self.media=self.dir/'media'
        self.media.mkdir()
        self.state=self.dir/'state'
        self.a=self.make('TV/American.Dad.S08E01.mkv')
        self.b=self.make('TV/American.Dad.S08E02.mkv')
        self.c=self.make('TV/American.Dad.S08E03.mkv')
        self.d=self.make('Movies/Bottoms.2023.mkv')
        self.e=self.make('TV/Other.Show.S01E01.mkv')
        self.outside=self.dir/'secret.mkv'
        self.outside.write_bytes(b'do not scan outside')
        self.items=[
            item(self.a,season=8,episode=1),
            item(self.b,season=8,episode=2),
            item(self.c,season=8,episode=3),
            item(self.d,type_='Movie'),
            item(self.e,season=1,episode=1),
            item(self.outside,type_='Movie')
        ]
        self.client=Client(self.items)

    def make(self,name):
        path=self.media/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'fictional video')
        return path

    def scan(self):
        return lib.scan(self.client,(self.media,),self.state,
            log=lambda *x:None,
            probe_fn=lambda *_: (_ for _ in ()).throw(
                AssertionError('MediaStreams available: no ffprobe needed')))

    def fill(self,budget=10,now=2000000000):
        return lib.fill(self.client,(self.media,),self.state,
            search_budget=budget,now=now,log=lambda *x:None)

    def good(self,video):
        return {'Id':video.stem+'-eng','ProviderName':'Subbuzz',
                'Format':'srt','ThreeLetterISOLanguageName':'eng',
                'IsHashMatch':True,'Name':video.stem+'.en',
                'DownloadCount':15}

    def set_success(self,*videos):
        for video in videos:
            idx=next(x['Id'] for x in self.items if x['Path']==str(video))
            self.client.results[idx]=[self.good(video)]

    def test_inventory_is_complete_scoped_and_does_not_search_providers(self):
        before={str(p):p.read_bytes()
                for p in self.media.rglob('*') if p.is_file()}
        counts=self.scan()
        self.assertEqual(counts['jellyfin_items'],6)
        self.assertEqual(counts['catalog_eligible_paths'],5)
        self.assertEqual(counts['missing'],5)
        self.assertEqual(lib.report(self.state,log=lambda *x:None)['total'],5)
        self.assertFalse(self.client.downloads)
        self.assertTrue(all('/RemoteSearch/' not in x for x in self.client.queries))
        self.assertEqual(before,{str(p):p.read_bytes()
                           for p in self.media.rglob('*') if p.is_file()})

    def test_existing_japanese_subtitles_preempt_english_acquisition(self):
        # Native Japanese in Jellyfin metadata is sufficient to skip EN.
        self.items[0]['MediaStreams'].append(
            {'Type':'Subtitle','Language':'jpn','Codec':'subrip',
             'IsForced':False})
        counts=self.scan()
        self.assertEqual(counts['japanese_present'],1)
        self.assertEqual(counts['missing'],4)
        result=self.fill()
        self.assertEqual(result['attempted'],4)
        searches=[x for x in self.client.queries if '/RemoteSearch/' in x]
        self.assertFalse(any(self.items[0]['Id'] in path for path in searches))

    def test_japanese_sidecar_appearing_after_inventory_skips_english(self):
        self.scan()
        target=self.a.parent/(self.a.stem+'.ja.srt')
        target.write_bytes(srt())
        self.set_success(self.a)
        result=self.fill(budget=1)
        self.assertEqual(result['outcomes']['japanese_present'],1)
        self.assertFalse(self.client.downloads)
        self.assertFalse(any('/RemoteSearch/' in x for x in self.client.queries))

    def test_existing_english_sidecar_and_embedded_english_are_ready(self):
        (self.a.parent/(self.a.stem+'.en.srt')).write_bytes(srt())
        self.items[1]['MediaStreams'].append(
            {'Type':'Subtitle','Language':'en','Codec':'ass','IsForced':False})
        counts=self.scan()
        self.assertEqual(counts['ready'],2)
        self.assertEqual(counts['missing'],3)
        results=self.fill()
        self.assertEqual(results['attempted'],3)
        self.assertFalse(self.client.downloads)
        paths=self.client.queries
        self.assertFalse(any('/RemoteSearch/' in x and self.items[0]['Id'] in x
                             for x in paths))
        self.assertFalse(any('/RemoteSearch/' in x and self.items[1]['Id'] in x
                             for x in paths))

    def test_pgs_bitmap_alone_does_not_count_as_usable_text(self):
        info={'MediaStreams':[{'Type':'Audio','Language':'eng'},
                {'Type':'Subtitle','Language':'eng','Codec':'hdmv_pgs_subtitle'}]}
        self.assertFalse(lib.item_streams(info)['has_en_text'])
        info['MediaStreams'][1]['Codec']='subrip'
        self.assertTrue(lib.item_streams(info)['has_en_text'])

    def test_strict_file_hash_required_no_generic_title_match(self):
        data=self.good(self.a)
        row={'media_type':'Episode','season':8,'episode':1}
        self.assertTrue(lib.hash_match(data,row))
        self.assertFalse(lib.hash_match({**data,'IsHashMatch':False},row))
        self.assertFalse(lib.hash_match({**data,'IsHashMatch':'true'},row))
        self.assertFalse(lib.hash_match({**data,'Format':'ass'},row))
        self.assertFalse(lib.hash_match({**data,
                          'ThreeLetterISOLanguageName':'jpn'},row))
        self.assertFalse(lib.hash_match({**data,'IsForced':True},row))
        self.assertFalse(lib.hash_match({**data,
                          'Name':'American.Dad.S19E01'},row))
        self.assertTrue(lib.hash_match({**data,
                         'Name':'release-without-episode-tag'},row))

    def test_hash_only_download_priority_s08_then_movies_and_tv(self):
        self.scan()
        self.set_success(self.a,self.b,self.c)
        result=self.fill(budget=2)
        self.assertEqual(result['outcomes']['downloaded'],2)
        self.assertEqual(len(self.client.downloads),2)
        self.assertTrue((self.a.parent/(self.a.stem+'.en.srt')).is_file())
        self.assertTrue((self.b.parent/(self.b.stem+'.en.srt')).is_file())
        self.assertFalse((self.c.parent/(self.c.stem+'.en.srt')).exists())
        self.assertFalse((self.d.parent/(self.d.stem+'.en.srt')).exists())
        self.assertEqual(self.fill(budget=2)['outcomes']['downloaded'],1)
        status=lib.report(self.state,log=lambda *x:None)
        self.assertEqual(status['american_dad_s08']['ready'],3)

    def test_failed_search_enters_cooldown_and_moves_forward_on_repeated_run(self):
        self.scan()
        first=self.fill(budget=2,now=2000000000)
        self.assertEqual(first['outcomes']['no_hash_match'],2)
        self.client.queries.clear()
        again=self.fill(budget=2,now=2000000001)
        self.assertEqual(again['outcomes']['no_hash_match'],2)
        searches=[x for x in self.client.queries if '/RemoteSearch/' in x]
        self.assertEqual(len(searches),2)
        self.assertTrue(all(self.items[i]['Id'] not in searches[0]+searches[1]
                            for i in range(2)))
        self.client.queries.clear()
        self.scan()  # No underlying file change, preserve search cooldown.
        self.fill(budget=1,now=2000000002)
        searches=[x for x in self.client.queries if '/RemoteSearch/' in x]
        self.assertEqual(len(searches),1)
        self.assertNotIn(self.items[0]['Id'],searches[0])

    def test_existing_media_same_fingerprint_reuses_metadata(self):
        self.scan()
        second=self.scan()
        self.assertEqual(second['cached'],5)
        self.assertEqual(second.get('refreshed',0),0)

    def test_sidecar_appearing_later_reclassifies_and_never_gets_overwritten(self):
        self.scan()
        target=self.a.parent/(self.a.stem+'.en.srt')
        target.write_bytes(srt())
        counts=self.scan()
        self.assertGreaterEqual(counts['ready'],1)
        self.set_success(self.a)
        self.fill(budget=3)
        self.assertEqual(target.read_bytes(),srt())
        self.assertFalse(any(self.items[0]['Id'] in x
                             for x in self.client.downloads))

    def test_deleted_video_is_skipped_and_not_offered_to_provider(self):
        self.scan()
        self.a.unlink()
        result=self.fill(budget=1)
        self.assertEqual(result['outcomes']['out_of_scope'],1)
        self.assertFalse(self.client.downloads)

    def test_catalog_number_conflict_is_held_before_search(self):
        self.items[0]['ParentIndexNumber']=19
        self.scan()
        result=self.fill(budget=1)
        self.assertEqual(result['outcomes']['numbering_conflict'],1)
        self.assertFalse(self.client.downloads)

    def test_download_saved_in_jellyfin_only_not_claimed_for_subhub(self):
        self.scan()
        self.client.write=False
        self.set_success(self.a)
        res=self.fill(budget=1)
        self.assertEqual(res['outcomes']['jellyfin_only'],1)
        self.assertFalse((self.a.parent/(self.a.stem+'.en.srt')).exists())
        second=self.fill(budget=1,now=2000000001)
        self.assertEqual(second['outcomes']['no_hash_match'],1)
        self.assertEqual(len(self.client.downloads),1)

    def test_jellyfin_rate_limit_stops_remaining_requests(self):
        self.scan()
        self.client.failure=HTTPError('http://invalid',429,'limit',{},None)
        response=self.fill(budget=10)
        self.assertEqual(response['outcomes']['rate_limited_or_unavailable'],1)
        searched=[x for x in self.client.queries if '/RemoteSearch/' in x]
        self.assertEqual(len(searched),1)

    def test_reject_nonapproved_path_and_symlink(self):
        link=self.media/'symlink.mkv'
        link.symlink_to(self.outside)
        self.items.append(item(link,type_='Movie'))
        counts=self.scan()
        self.assertGreaterEqual(counts['out_of_scope_or_missing'],2)

    def test_interrupted_large_scan_preserves_committed_cache(self):
        videos=[self.make('LongSeries/Show.S01E%03d.mkv'%i)
                for i in range(1,102)]
        catalog={str(video):{
            'Type':'Episode','Id':'episode%04d'%n,'Path':str(video),
            'Name':video.stem,'IndexNumber':n,'ParentIndexNumber':1}
            for n,video in enumerate(videos,1)}
        calls=[]
        def probe(video):
            calls.append(video)
            if len(calls)==101:
                raise KeyboardInterrupt()
            return {'embedded_en':None,'audio_en':True}
        with self.assertRaises(KeyboardInterrupt):
            lib.scan(self.client,(self.media,),self.state,probe_fn=probe,
                     catalog_fn=lambda client:catalog,log=lambda *x:None)
        result=lib.report(self.state,log=lambda *x:None)
        self.assertEqual(result['total'],100)
        self.assertEqual(result['states']['missing'],100)

    def test_no_translation_engine_or_global_jellyfin_task_calls(self):
        self.scan()
        self.set_success(self.a)
        self.fill(budget=1)
        self.assertFalse(any('/ScheduledTasks' in x for x in self.client.queries))
        self.assertFalse(any('/ScheduledTasks' in x for x in self.client.downloads))
        self.assertEqual(list(self.state.rglob('*.ja.srt')),[])
        self.assertEqual(list(self.media.rglob('*.ja.srt')),[])

    def test_provider_budget_must_be_bounded(self):
        self.scan()
        for value in (0,31,-1):
            with self.assertRaises(ValueError):
                self.fill(budget=value)


if __name__=='__main__':
    unittest.main()
