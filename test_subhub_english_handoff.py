"""No-provider, no-GPU checks for source-first English-to-PLaMo handoff."""
import json
from pathlib import Path
import subprocess
import sys
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


if __name__=="__main__":
    unittest.main()
