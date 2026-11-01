"""No media or model dependencies; synthetic title inventory and probe tests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import library_census as lc


class LibraryCensusTests(unittest.TestCase):
    def test_classifies_actual_sidecars_and_missing_source(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for name in ('film-a.mkv','film-b.mkv','film-c.mkv','film-d.mkv',
                         'film-e.mkv','film-f.mkv','film-g.mkv'):
                (root/name).write_bytes(b'video')
            (root/'film-a.Japanese Editorial.ja.srt').write_text('JA')
            (root/'film-b.en.srt').write_text('EN')
            (root/'film-c.fr.srt').write_text('French')
            (root/'film-f.eng.ass').write_text('EN')
            # Not a matching film sidecar, should not be treated as Japanese.
            (root/'film-h.ja.srt').write_text('unrelated')
            def fake_probe(path):
                result={'ok':True,'audio_lang':'eng','audio_en':True,
                        'ja':False,'en_text':False,'en_image':False,
                        'en_unknown_codec':False}
                if path.name=='film-c.mkv':result['en_image']=True
                if path.name=='film-d.mkv':result['ja']=True
                if path.name=='film-e.mkv':result['audio_en']=False
                if path.name=='film-g.mkv':result['ok']=False
                return result
            data=lc.census([root],probe_fn=fake_probe)
            statuses={Path(x['path']).stem:x['status'] for x in data['videos']}
            self.assertEqual(statuses,{
                'film-a':'existing_ja_sidecar',
                'film-b':'ready_english_text',
                'film-c':'needs_english_ocr',
                'film-d':'existing_ja_embedded',
                'film-e':'audio_not_verified_english',
                'film-f':'ready_english_text',
                'film-g':'needs_metadata_review'
            })
            self.assertEqual(data['total_videos'],7)
            self.assertEqual(data['total_bytes'],35)

    def test_no_manifest_without_opt_in_and_exclusive_private_export(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            (root/'movie.mkv').write_bytes(b'fake')
            def fake_probe(path):
                return {'ok':True,'audio_lang':'eng','audio_en':True,
                        'ja':False,'en_text':True,'en_image':False,
                        'en_unknown_codec':False}
            data=lc.census([root],probe_fn=fake_probe)
            self.assertEqual(sorted(p.name for p in root.iterdir()),['movie.mkv'])
            output=root/'private.json'
            lc.save_private(output,data)
            self.assertEqual(json.loads(output.read_text())['total_videos'],1)
            with self.assertRaises(FileExistsError):
                lc.save_private(output,data)
            self.assertEqual(json.loads(output.read_text())['total_videos'],1)

    def test_probe_recognizes_embedded_text_image_and_japanese(self):
        streams={'streams':[
            {'codec_type':'audio','tags':{'language':'eng'},'disposition':{'default':1}},
            {'codec_type':'subtitle','codec_name':'subrip','tags':{'language':'eng'}},
            {'codec_type':'subtitle','codec_name':'hdmv_pgs_subtitle','tags':{'language':'eng'}},
            {'codec_type':'subtitle','codec_name':'ass','tags':{'language':'jpn'}}]}
        class Result:
            returncode=0
            stdout=json.dumps(streams)
        with patch.object(lc.subprocess,'run',return_value=Result()) as call:
            x=lc.probe(Path('/movie.mkv'))
        self.assertTrue(x['audio_en'])
        self.assertTrue(x['en_text'])
        self.assertTrue(x['en_image'])
        self.assertTrue(x['ja'])
        self.assertEqual(call.call_args.kwargs['timeout'],12)

    def test_probe_failure_cannot_count_film_as_ready(self):
        class Bad:
            returncode=1
            stdout=''
        with patch.object(lc.subprocess,'run',return_value=Bad()):
            info=lc.probe(Path('/movie.mkv'))
        self.assertEqual(lc.classify({'en'},info),'needs_metadata_review')

    def test_limit_and_symlink_do_not_automatically_queue(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            (root/'a.mkv').write_bytes(b'x')
            (root/'b.mkv').write_bytes(b'x')
            (root/'c.mkv').symlink_to(root/'a.mkv')
            d=lc.census([root],lim=1,probe_fn=lambda p:{
                'ok':False,'audio_lang':'unknown','audio_en':False,
                'ja':False,'en_text':False,'en_image':False,'en_unknown_codec':False
            })
            self.assertEqual(d['total_videos'],1)
            self.assertEqual(d['status_counts']['needs_metadata_review'],1)


if __name__=='__main__':
    unittest.main()
