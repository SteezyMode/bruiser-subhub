"""No-provider, no-GPU checks for source-first English-to-PLaMo handoff."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools import subhub_plamo_handoff as handoff


class EnglishHandoffTests(unittest.TestCase):
    def test_missing_english_searches_exact_jellyfin_movie_and_not_wrong_hash(self):
        jid="a"*32
        video=Path("/mnt/2TB/Plex Expansion/Movies/Horror/Film.mkv")
        class Client:
            def __init__(self):
                self.posts=[]
            def get(self,route):
                if route=="/Items/"+jid:
                    return {"Id":jid,"Path":str(video),"Type":"Movie"}
                if route=="/Items/"+jid+"/RemoteSearch/Subtitles/eng":
                    return [
                        {"IsHashMatch":False,"Id":"bad","ProviderName":"Fake",
                         "Format":"srt","ThreeLetterISOLanguageName":"eng"},
                        {"IsHashMatch":True,"Id":"approved","ProviderName":"Provider",
                         "Format":"srt","ThreeLetterISOLanguageName":"eng"}]
                raise AssertionError(route)
            def post(self,route):
                self.posts.append(route)
        client=Client()
        source=SimpleNamespace(NativeJellyfin=lambda:client)
        handoff.acquire_exact_english(video,jid,"Movie",source)
        self.assertEqual(client.posts,[
            "/Items/"+jid+"/RemoteSearch/Subtitles/approved"])
        with self.assertRaisesRegex(RuntimeError,"english_search_requires_exact_jellyfin"):
            handoff.acquire_exact_english(video,"invalid","Movie",source)

    def test_english_sourcing_refuses_misnumbered_episode(self):
        jid="b"*32
        video=Path("/media/TV/Show.S01E05.mkv")
        class Client:
            def get(self,route):
                if route=="/Items/"+jid:
                    return {"Id":jid,"Path":str(video),"Type":"Episode",
                            "ParentIndexNumber":1,"IndexNumber":5}
                return [{"IsHashMatch":True,"Id":"wrong","ProviderName":"Provider",
                         "Format":"srt","ThreeLetterISOLanguageName":"eng",
                         "Name":"Different.Release.S01E04.mkv"}]
            def post(self,route):
                raise AssertionError("wrong-episode download")
        with self.assertRaisesRegex(RuntimeError,"no_exact_video_hash_english"):
            handoff.acquire_exact_english(
                video,jid,"Episode",SimpleNamespace(NativeJellyfin=Client))

    def test_ffsubsync_success_does_not_run_alass(self):
        raw=b"sample"
        source=SimpleNamespace(validate_timing_source=lambda *a:
                               (b"synced",{"mode":"audio_verified_ffsubsync"}))
        result=handoff.synchronize_external_english(
            Path("/tmp/video.mkv"),raw,source,None)
        self.assertEqual(result[0],b"synced")

    def test_ffsubsync_failure_can_use_alass_on_exact_video(self):
        raw=b"English source"
        video=Path("/tmp/film.mkv")
        src=SimpleNamespace(validate_timing_source=lambda *args:
                            (_ for _ in ()).throw(RuntimeError("bad_ffsync")))
        alass=SimpleNamespace(available=lambda:True,
             align=lambda v,b:(b"aligned","video_audio"),
             assess=lambda before,after,runtime:{
                 "shift_min_s":-1.0,"shift_max_s":2.0,"cues":300})
        fake_probe=subprocess.CompletedProcess([],0,stdout="3600.0\n")
        with patch.dict(sys.modules,{"ja_first_alass":alass}), \
             patch.object(handoff.subprocess,"run",return_value=fake_probe):
            aligned,meta=handoff.synchronize_external_english(
                video,raw,src,SimpleNamespace(
                    keep_source_dialogue=lambda original,new:new))
        self.assertEqual(aligned,b"aligned")
        self.assertEqual(meta["mode"],"audio_aligned_alass")
        self.assertEqual(meta["metrics"]["cues"],300)

    def test_neither_sync_engine_can_approve_english(self):
        source=SimpleNamespace(validate_timing_source=lambda *args:
             (_ for _ in ()).throw(RuntimeError("bad_ffsync")))
        fake=SimpleNamespace(available=lambda:False)
        with patch.dict(sys.modules,{"ja_first_alass":fake}):
            with self.assertRaisesRegex(RuntimeError,"english_audio_alignment_failed"):
                handoff.synchronize_external_english(
                    Path("/tmp/film.mkv"),b"bad english",source,None)


    def test_automatic_movie_untagged_audio_uses_local_detection(self):
        video=Path("/tmp/film.mkv")
        with patch.object(handoff,"movie_audio_track",return_value=(1,"und",3600)), \
             patch.object(handoff,"whisper_movie") as whisper:
            handoff.verify_automatic_movie_audio(video)
            whisper.assert_called_once_with(video,"detect",track=(1,"und",3600))

    def test_automatic_movie_known_foreign_audio_not_overridden(self):
        with patch.object(handoff,"movie_audio_track",return_value=(1,"jpn",3600)), \
             patch.object(handoff,"whisper_movie") as whisper:
            with self.assertRaisesRegex(RuntimeError,"known_non_english"):
                handoff.verify_automatic_movie_audio(Path("/tmp/film.mkv"))
            whisper.assert_not_called()

    def test_automatic_movie_no_hash_falls_back_to_private_asr(self):
        raw=b"generated English"
        cues=[{"number":i} for i in range(1,151)]
        daily=SimpleNamespace(already_ja=lambda v:False,english_srt=lambda v:None)
        small=SimpleNamespace(parse_srt=lambda *a,**kw:cues)
        info={"audio_en":True,"ja":False,"embedded_en":None}
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/"movie.mkv"
            video.write_bytes(b"fixture")
            with patch.object(handoff,"indexed_jellyfin_english",return_value=None), \
                 patch.object(handoff,"acquire_exact_english",side_effect=RuntimeError(
                     "no_exact_video_hash_english_srt_found")), \
                 patch.object(handoff,"whisper_movie",return_value=raw) as whisper:
                out=handoff.saved_media(video,"a"*32,info,daily,None,small,None,
                    Path,kind="Movie",automatic_movie=True)
                whisper.assert_called_once_with(video,"transcribe")
                self.assertEqual(out[3],"local_whisper_exact_audio")
                self.assertEqual(out[1],cues)
                self.assertEqual(list(Path(folder).iterdir()),[video])

    def test_automatic_movie_provider_failure_does_not_authorize_asr(self):
        daily=SimpleNamespace(already_ja=lambda v:False,english_srt=lambda v:None)
        info={"audio_en":True,"ja":False,"embedded_en":None}
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/"movie.mkv"
            video.write_bytes(b"fixture")
            with patch.object(handoff,"indexed_jellyfin_english",return_value=None), \
                 patch.object(handoff,"acquire_exact_english",side_effect=RuntimeError(
                     "provider_unavailable")), \
                 patch.object(handoff,"whisper_movie") as whisper:
                with self.assertRaisesRegex(RuntimeError,"provider_unavailable"):
                    handoff.saved_media(video,"a"*32,info,daily,None,None,None,
                        Path,kind="Movie",automatic_movie=True)
                whisper.assert_not_called()


if __name__=="__main__":
    unittest.main()
