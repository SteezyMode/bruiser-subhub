"""No-network tests for Japanese subtitle presence in movie search."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import subhub_dashboard_server as dashboard


class MovieCoverageTests(unittest.TestCase):
    def test_real_sidecar_and_embedded_subtitles_are_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            video=Path(temp)/"A History of Violence (2005).mkv"
            video.write_bytes(b"fixture only")
            subtitle=video.with_name(video.stem+".jpn.srt")
            subtitle.write_text("Japanese")
            status,_=dashboard.movie_subtitle_status(video)
            self.assertEqual(status,"present")
            subtitle.unlink()
            subtitle=video.with_name(video.stem+".ja.forced.srt")
            subtitle.write_text("Sign only")
            good=subprocess.CompletedProcess([],0,stdout=json.dumps({
                "streams":[{"codec_type":"subtitle","tags":{"language":"jpn"},
                            "disposition":{"forced":0}}]}).encode())
            status,detail=dashboard.movie_subtitle_status(
                video,runner=lambda *args,**kw:good)
            self.assertEqual((status,detail),("present","Japanese subtitle embedded in video"))
            other=subprocess.CompletedProcess([],0,stdout=json.dumps({
                "streams":[{"codec_type":"subtitle","tags":{"language":"eng"},
                            "disposition":{"forced":0}}]}).encode())
            status,_=dashboard.movie_subtitle_status(video,runner=lambda *args,**kw:other)
            self.assertEqual(status,"missing")

    def test_jellyfin_inventory_subtitle_presence_is_visible_in_movie_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            video=root/"A History of Violence (2005).mkv"
            video.write_bytes(b"fixture only")
            prior={
                str(video):{
                    "jellyfin_inventory_status":"existing_japanese_subtitle",
                    "jellyfin_inventory_generated":"2026-11-11T00:00:00+00:00",
                    "jellyfin_id":"a"*32,
                }}
            with patch.object(dashboard,"movie_queue_evidence",return_value={}), \
                 patch.object(dashboard,"movie_jellyfin_inventory",return_value=prior), \
                 patch.object(dashboard,"movie_subtitle_status",
                              return_value=("missing","No Japanese subtitle detected")):
                rows=dashboard.search_movie_files("A History of Violence",roots=(root,))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["japanese_status"],"present")
            self.assertIn("Jellyfin inventory",rows[0]["japanese_detail"])

    def test_movie_plamo_cannot_run_from_provider_error_or_unchecked_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            video=root/"Film.mkv";video.write_bytes(b"fixture")
            jid="a"*32
            with patch.object(dashboard,"MOVIE_ROOTS",(root,)), \
                 patch.object(dashboard,"movie_subtitle_status",
                              return_value=("missing","No Japanese track")), \
                 patch.object(dashboard,"movie_queue_evidence",
                              return_value={str(video):{
                                  "jellyfin_id":jid,"fallback_ready":True,
                                  "search_outcome":"error"}}), \
                 patch.object(dashboard.subprocess,"run",
                              side_effect=AssertionError("must not start worker")):
                with self.assertRaisesRegex(RuntimeError,"verified_japanese_fallback"):
                    dashboard.start_movie_translation(
                        {"video":str(video),"jellyfin_id":jid})


if __name__=="__main__":
    unittest.main()
