"""Offline validation of CPU-only Whisper English source fallback."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import english_asr_fallback as asr
from tools import daily_japanese as intake


class FakeModel:
    def __init__(self,*args,**kwargs):
        assert args==('small.en',)
        assert kwargs['device']=='cpu'
        assert kwargs['compute_type']=='int8'
        assert kwargs['cpu_threads']<=3
        self.options=kwargs
    def transcribe(self,audio,**kwargs):
        assert Path(audio).is_file()
        assert kwargs['language']=='en'
        assert kwargs['word_timestamps'] is True
        segs=[]
        for i in range(80):
            w=SimpleNamespace(start=i*9.0+0.2,
                end=i*9.0+1.7,
                word='Ordinary English dialogue')
            segs.append(SimpleNamespace(words=[w]))
        return iter(segs),SimpleNamespace(language='en')


class ASRFallbackTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.video=self.root/'American.Dad.S08E01.mkv'
        self.video.write_bytes(b'fictional video')
        self.state=self.root/'state'
        self.original=self.video.read_bytes()
        self.converted=[]
    def runner(self,cmd,**kw):
        self.converted.append(cmd)
        if cmd[0]=='ffprobe':
            if any('stream=' in part for part in cmd):
                return SimpleNamespace(
                    returncode=0,stdout=json.dumps({'streams':[
                        {'codec_type':'audio','index':0,
                         'tags':{'language':'jpn'},
                         'disposition':{'default':0}},
                        {'codec_type':'audio','index':1,
                         'tags':{'language':'eng'},
                         'disposition':{'default':1}}
                    ]}))
            return SimpleNamespace(returncode=0,stdout='1200.00\n')
        if cmd[0]=='ffmpeg':
            self.assertEqual(cmd[cmd.index('-map')+1],'0:1')
            Path(cmd[-1]).write_bytes(b'\x00'*70000)
            return SimpleNamespace(returncode=0,stdout='',stderr='')
        raise AssertionError('Unexpected executable')

    def test_valid_wav_and_whisper_create_readable_en_srt(self):
        with patch.object(intake.service,'secure_video'),patch.object(
            asr.intake,'probe',
            return_value={'ja':False,'audio_en':True,'embedded_en':None}):
            result=asr.transcribe(
                self.video,model_loader=FakeModel,runner=self.runner,
                state=self.state,download_root=self.state/'models')
        self.assertEqual(result,'published_en_draft')
        new=asr.source_path(self.video)
        self.assertTrue(new.is_file())
        self.assertIsNotNone(intake.english_srt(self.video))
        rows=intake.service.parse_srt(new.read_bytes())
        self.assertEqual(len(rows),80)
        self.assertEqual(self.video.read_bytes(),self.original)
        self.assertFalse(any('cuda' in str(x) for x in self.converted))
        self.assertEqual(list(self.state.glob('extract-*')),[])

    def test_preserve_previous_english_before_any_model_call(self):
        existing=self.video.with_name(self.video.stem+'.en.srt')
        existing.write_text('editorial english')
        with patch.object(intake.service,'secure_video'),patch.object(
            asr.intake,'probe',
            return_value={'ja':False,'audio_en':True,'embedded_en':None}):
            result=asr.transcribe(
                self.video,model_loader=lambda *a,**k:1,
                runner=self.runner,state=self.state)
        self.assertEqual(result,'skipped_en')
        self.assertEqual(existing.read_text(),'editorial english')
        self.assertFalse(self.converted)

    def test_existing_japanese_skips_before_model(self):
        ja=self.video.with_name(self.video.stem+'.ja.srt')
        ja.write_text('existing JA')
        with patch.object(intake.service,'secure_video'):
            result=asr.transcribe(
                self.video,model_loader=lambda *a,**k:1,
                runner=self.runner,state=self.state)
        self.assertEqual(result,'skipped_ja')
        self.assertFalse(self.converted)

    def test_atomic_create_only_never_overwrites_existing_source(self):
        target=asr.source_path(self.video)
        target.write_bytes(b'preserve me')
        self.assertFalse(asr.write_create_only(target,b'replace'))
        self.assertEqual(target.read_bytes(),b'preserve me')
        target.unlink()
        target.symlink_to(self.video)
        self.assertFalse(asr.write_create_only(target,b'replace'))
        self.assertEqual(self.video.read_bytes(),self.original)

    def test_no_nonenglish_default_even_if_second_track_english(self):
        def bad_runner(cmd,**kw):
            if any('stream=' in part for part in cmd):
                return SimpleNamespace(returncode=0,stdout=json.dumps({
                    'streams':[{'codec_type':'audio','index':0,
                        'tags':{'language':'jpn'},
                        'disposition':{'default':1}},
                        {'codec_type':'audio','index':1,
                        'tags':{'language':'eng'},
                        'disposition':{'default':0}}]}))
            raise AssertionError('duration should not be probed')
        with self.assertRaisesRegex(ValueError,'not explicitly labeled English'):
            asr.audio_source(self.video,runner=bad_runner)

    def test_srt_validation_rejects_zero_or_undersized_transcripts(self):
        for count in (0,1,49):
            segs=[SimpleNamespace(words=[SimpleNamespace(
                start=float(i),end=float(i)+0.4,word='a word')])
                for i in range(count)]
            with self.assertRaisesRegex(ValueError,'density'):
                asr.render(asr.cues_from_segments(segs,1200))

    def test_nonintersecting_cue_time_range_and_word_wrap(self):
        words=[
            SimpleNamespace(start=0.4,end=1.6,word='Hello'),
            SimpleNamespace(start=0.4,end=1.6,word='world'),
            SimpleNamespace(start=3.4,end=4.6,word='again')
        ]
        segments=[SimpleNamespace(words=words)]
        cues=asr.cues_from_segments(segments,1200)
        self.assertGreater(len(cues),0)
        self.assertEqual([a for a,b,v in cues],sorted(a for a,b,v in cues))
        self.assertTrue(all(b>a for a,b,v in cues))

    def test_timestamps_accurate(self):
        self.assertEqual(asr.fmt(0),'00:00:00,000')
        self.assertEqual(asr.fmt(61520),'00:01:01,520')
        self.assertEqual(asr.fmt(3600042),'01:00:00,042')


if __name__=='__main__':
    unittest.main()
