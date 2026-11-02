"""Synthetic, network-free tests of scoped Jellyfin English subtitle acquisition."""
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from tools import jellyfin_english_sources as jf


def synthetic_srt(n=25):
    def time(i):
        return '%02d:%02d:%02d,000'%(i//3600,i//60%60,i%60)
    return ('\n\n'.join(
        '%d\n%s --> %s\nOrdinary English line.'%(i+1,time(i*3),time(i*3+2))
        for i in range(n))+'\n').encode()


class DummyJellyfin:
    def __init__(self,video,results=None,meta=None,write=True):
        self.video=video
        self.results=results or []
        self.meta=meta or {}
        self.write=write
        self.gets=[]
        self.posts=[]
    def get(self,route):
        self.gets.append(route)
        if route.startswith('/Items?'):
            return {'Items':[dict(Id='e01',Path=str(self.video),
                    IndexNumber=1,ParentIndexNumber=8)],
                    'TotalRecordCount':1}
        if '/RemoteSearch/Subtitles/eng' in route:
            return self.results
        if route=='/Users/Me':
            return {'Policy':{'IsAdministrator':True}}
        raise AssertionError('Unexpected remote request '+route)
    def post(self,route,data=None):
        self.posts.append((route,data))
        if self.write:
            target=self.video.with_name(self.video.stem+'.en.srt')
            target.write_bytes(synthetic_srt())
        return None


class JellyfinSourceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder=Path(tmp.name)
        self.movie=self.folder/'American.Dad.S08E01.mkv'
        self.movie.write_bytes(b'cartoon media')
        self.extra=self.folder/'American.Dad.S09E01.mkv'
        self.extra.write_bytes(b'cartoon 9')
        self.other=self.folder/'Bottoms.2023.mkv'
        self.other.write_bytes(b'unrelated movie')
        self.root=self.folder/'state'
        self.calls=[]
        self.correct={
            'Id':'srt/odd%name','ProviderName':'Subbuzz',
            'Name':'American.Dad.S08E01.720p.WEB.x264',
            'Format':'srt','ThreeLetterISOLanguageName':'eng',
            'IsHashMatch':False,'DownloadCount':22}
        self.wrong={
            **self.correct,'Id':'bad',
            'Name':'American.Dad.S08E02.720p.WEB.x264'}
        self.client=DummyJellyfin(self.movie,[self.wrong,self.correct])

    def process(self,**kwargs):
        def fetch(roots,seasons):
            self.assertEqual(tuple(seasons),(8,))
            return {(8,1):[self.movie]}
        return jf.process((self.folder,),self.root,(8,),self.client,
            discover_fn=fetch,stdout=lambda *x:self.calls.append(x),
            **kwargs)

    def test_strong_episode_number_guard(self):
        self.assertFalse(jf.strong_match(self.wrong,8,1,self.movie))
        self.assertTrue(jf.strong_match(self.correct,8,1,self.movie))
        self.assertFalse(jf.strong_match({**self.correct,'Format':'ass'},8,1,self.movie))
        self.assertFalse(jf.strong_match({**self.correct,
                           'ThreeLetterISOLanguageName':'jpn'},8,1,self.movie))
        self.assertFalse(jf.strong_match({**self.correct,
                           'Name':'American.Dad.S19E01'},8,1,self.movie))
        self.assertFalse(jf.strong_match({**self.correct,
                           'Name':'Other.S08E01'},8,1,self.movie))
        self.assertTrue(jf.strong_match({**self.correct,
                           'Name':'Unknown Release','IsHashMatch':True},8,1,self.movie))
        self.assertFalse(jf.strong_match({**self.correct,
                           'Name':'Unknown Release','IsHashMatch':False},8,1,self.movie))

    def test_download_only_requested_exact_episode_then_start_existing_worker(self):
        backgrounds=[]
        def launch(*args):
            backgrounds.append(args)
            return {'pid':111,'log':'/private/log'}
        with patch.object(jf.intake,'probe',return_value={
             'audio_en':True,'ja':False,'embedded_en':None}):
            result=self.process(apply=True,start=True,background=launch)
        self.assertEqual(result['new_english_sources'],1)
        self.assertEqual(result['categories'],{'acquired':1})
        self.assertEqual(len(self.client.posts),1)
        self.assertTrue(self.client.posts[0][0].startswith(
            '/Items/e01/RemoteSearch/Subtitles/'))
        self.assertIn('srt%2Fodd%25name',self.client.posts[0][0])
        self.assertEqual(backgrounds[0][1],(8,))
        self.assertEqual(backgrounds[0][2:],(50,480))
        self.assertIsNone(next((x for x in self.calls if x[0]=='EN_SOURCE'
                                and 'S19' in x[1]),None))

    def test_preview_is_read_only_and_never_searches_providers(self):
        result=self.process()
        self.assertEqual(result['categories'],{'jellyfin_registered':1})
        self.assertFalse(self.client.posts)
        self.assertFalse(any('RemoteSearch' in x for x in self.client.gets))
        self.assertFalse(list(self.folder.glob('*.srt')))

    def test_missing_provider_results_do_not_launch(self):
        self.client.results=[self.wrong]
        starts=[]
        with patch.object(jf.intake,'probe',return_value={
             'audio_en':True,'ja':False,'embedded_en':None}):
            res=self.process(apply=True,start=True,
                             background=lambda *x: starts.append(x))
        self.assertEqual(res['categories'],{'no_strong_provider_match':1})
        self.assertFalse(starts)
        self.assertFalse(self.client.posts)

    def test_download_without_sidecar_does_not_count_as_ready(self):
        self.client.write=False
        with patch.object(jf.intake,'probe',return_value={
             'audio_en':True,'ja':False,'embedded_en':None}):
            res=self.process(apply=True)
        self.assertEqual(res['categories'],{'not_saved_beside_video':1})
        self.assertEqual(res['new_english_sources'],0)

    def test_protect_existing_japanese_and_existing_english(self):
        existing_ja=self.movie.with_name(self.movie.stem+'.ja.srt')
        existing_ja.write_bytes(b'editorial track')
        result=self.process(apply=True)
        self.assertEqual(result['categories'],{'existing_japanese':1})
        self.assertFalse(self.client.posts)
        existing_ja.unlink()
        en=self.movie.with_name(self.movie.stem+'.eng.srt')
        en.write_bytes(synthetic_srt())
        result=self.process(apply=True)
        self.assertEqual(result['categories'],{'existing_english':1})
        self.assertFalse(self.client.posts)

    def test_no_item_path_match_is_not_fuzzily_resolved(self):
        catalog={str(self.other):[dict(Id='x',IndexNumber=1,
                                      ParentIndexNumber=8)]}
        res=jf.process((self.folder,),self.root,(8,),self.client,
            discover_fn=lambda *x:{(8,1):[self.movie]},
            catalog_fn=lambda *x:catalog,apply=True,
            stdout=lambda *x:None)
        self.assertEqual(res['categories'],
                         {'not_registered_or_numbering_conflict':1})
        self.assertFalse(self.client.posts)

    def test_jellyfin_season_metadata_mismatch_blocks_retrieval(self):
        fake={str(self.movie.resolve()):[dict(Id='episode',
                                             IndexNumber=1,
                                             ParentIndexNumber=19)]}
        res=jf.process((self.folder,),self.root,(8,),self.client,
            discover_fn=lambda *x:{(8,1):[self.movie]},
            catalog_fn=lambda *x:fake,apply=True,
            stdout=lambda *x:None)
        self.assertGreaterEqual(res['categories']['jellyfin_numbering_conflict'],1)
        self.assertFalse(self.client.posts)

    def test_private_cached_access_token_permissions(self):
        path=self.folder/'private-token.json'
        jf.save_token('testonly-token','bruiser-testing-id',path)
        token=jf.load_token(path)
        self.assertEqual(token['token'],'testonly-token')
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError,'permissions'):
            jf.load_token(path)

    def test_authentication_reuses_existing_private_token_no_prompt(self):
        path=self.folder/'access.json'
        jf.save_token('existing-testing-token','bruiser-testing-id',path)
        client=jf.Jellyfin()
        with patch.object(client,'get',
             return_value={'Policy':{'IsAdministrator':True}}):
            self.assertEqual(jf.authenticate(client,path), 'cached')
        self.assertEqual(client.token,'existing-testing-token')

    def test_authentication_never_stores_password(self):
        path=self.folder/'token.json'
        client=jf.Jellyfin()
        with patch.object(client,'login') as login,patch.object(
             jf.sys.stdin,'isatty',return_value=True):
            def fake_login(u,p):
                self.assertEqual((u,p),('admin','private-pass'))
                client.token='token-not-password'
            login.side_effect=fake_login
            self.assertEqual(jf.authenticate(
                client,path,lambda s:'admin',
                lambda s:'private-pass'),'interactive')
        self.assertNotIn('private-pass',path.read_text())
        self.assertEqual(jf.load_token(path)['token'],'token-not-password')


if __name__=='__main__':
    unittest.main()
