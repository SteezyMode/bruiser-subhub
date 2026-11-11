"""Offline regression for reusable Jellyfin-native series/movie source controls.

No provider calls, no real systemd services, no media/DB changes.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import subhub_jellyfin_batch as batch
from tools import subhub_dashboard_server as dashboard


def tv(jid,season,episode,*,status="ready_ja_search",series="Example Show"):
    return {"jellyfin_id":jid,"kind":"Episode","title":f"Episode {episode}",
            "series_title":series,"season":season,"episode":episode,
            "status":status,"host_path":"/unused/media/video.mkv"}


def movie(jid,title,*,status="ready_ja_search"):
    return {"jellyfin_id":jid,"kind":"Movie","title":title,
            "status":status,"host_path":"/unused/media/film.mkv"}


class GenericJellyfinBatch(unittest.TestCase):
    def setUp(self):
        batch.STOP=False
        self.rows=[tv("a"*32,1,1),tv("b"*32,1,2),tv("c"*32,2,1),
                   tv("d"*32,2,2,status="existing_japanese_subtitle"),
                   tv("e"*32,1,1,series="Other Show"),
                   movie("f"*32,"Bride of Chucky"),
                   movie("1"*32,"Step Brothers")]

    def test_serialize_any_selected_series_seasons_episodes_and_movies(self):
        all_s=batch.choose(self.rows,series="Example Show")
        self.assertEqual(len(all_s),3)
        self.assertEqual([x["jellyfin_id"] for x in
                          batch.choose(self.rows,series="Example Show",seasons=[2])],
                         ["c"*32])
        self.assertEqual([x["jellyfin_id"] for x in
                          batch.choose(self.rows,series="Example Show",picks=[(1,2)])],
                         ["b"*32])
        self.assertEqual(len(batch.choose(self.rows,movie_ids=["1"*32,"f"*32])),2)
        with self.assertRaisesRegex(ValueError,"Jellyfin_catalog"):
            batch.choose(self.rows,series="Example Show",picks=[(99,2)])
        with self.assertRaises(ValueError):
            batch.choose(self.rows,series="Nonexistent Show")
        with self.assertRaises(ValueError):
            batch.choose(self.rows,movie_ids=["f"*32,"f"*32])

    def test_completed_source_batch_and_exact_id_no_direct_jellyfin_write(self):
        rows=batch.choose(self.rows,series="Example Show",seasons=[1])
        plan=batch.selector(series="Example Show",seasons=[1])
        state=batch.fresh_state(rows,plan,now=12345)
        calls=[]
        def runner(cmd,*,timeout):
            calls.append((cmd,timeout))
            if "ja_first_stage_jellyfin.py" in " ".join(cmd):
                self.assertEqual(cmd[cmd.index("--jellyfin-id")+1],
                                 rows[len(calls)//2]["jellyfin_id"])
                return 0,("JELLYFIN_JA_SEARCH_REQUEST: id\n"
                          "JELLYFIN_PRIVATE_STAGE: {\"status\":\"staged_not_published\"}"),""
            return 0,('BRUISER_PUBLISH_ITEM: {"jellyfin_id": "'+
                      cmd[cmd.index("--jellyfin-id")+1]+
                      '", "proof": "ready_ffsubsync", "result": "published"}'),""
        with patch.object(batch.stage,"japanese_sidecar_exists",return_value=False), \
             patch.object(batch.time,"sleep"):
            batch.execute(rows,state,limit=20,runner=runner,writer=lambda doc:None)
        self.assertEqual(state["state"],"completed")
        self.assertEqual(batch.progress(state)["published"],2)
        self.assertEqual(state["searches_this_run"],2)
        self.assertEqual(state["downloads_this_run"],2)
        self.assertEqual(len(calls),4)
        self.assertTrue(all("--apply" in cmd for cmd,_ in calls))
        self.assertTrue(all("RemoteSearch" not in " ".join(cmd) for cmd,_ in calls))

    def test_limit_pause_and_continue_without_repeating_previous_item(self):
        rows=batch.choose(self.rows,series="Example Show")
        selection=batch.selector(series="Example Show")
        now=int(time.time())
        state=batch.fresh_state(rows,selection,now=now)
        calls=[]
        def runner(cmd,*,timeout):
            calls.append(cmd)
            return 0,"JELLYFIN_JA_SEARCH_REQUEST: id\nHELD: no exactly matching Japanese SRT",""
        with patch.object(batch.stage,"japanese_sidecar_exists",return_value=False), \
             patch.object(batch.time,"sleep"):
            batch.execute(rows,state,limit=1,runner=runner,writer=lambda doc:None)
        self.assertEqual(state["state"],"paused")
        self.assertEqual(state["searches_this_run"],1)
        self.assertEqual(batch.progress(state)["pending"],2)
        second=batch.fresh_state(rows,selection,state,now=now+1)
        self.assertEqual(second["items"][0]["status"],"no_match")
        self.assertEqual(second["items"][1]["status"],"queued")
        with patch.object(batch.stage,"japanese_sidecar_exists",return_value=False), \
             patch.object(batch.time,"sleep"):
            batch.execute(rows,second,limit=1,runner=runner,writer=lambda doc:None)
        self.assertEqual(len(calls),2)
        self.assertEqual(second["searches_this_run"],1)
        stale=batch.fresh_state(rows,selection,second,now=now+21*3600)
        self.assertEqual(stale["items"][0]["status"],"queued")

    def test_quota_exhaustion_halts_the_batch_not_marked_as_absence(self):
        rows=batch.choose(self.rows,series="Example Show")
        state=batch.fresh_state(rows,batch.selector(series="Example Show"),now=100000)
        with patch.object(batch.stage,"japanese_sidecar_exists",return_value=False):
            batch.execute(rows,state,limit=20,runner=lambda cmd,timeout:(
                1,"JELLYFIN_JA_SEARCH_REQUEST: id","HTTP Error 429: Too Many Requests"),
                writer=lambda doc:None)
        self.assertEqual(state["state"],"paused")
        self.assertEqual(state["items"][0]["status"],"deferred")
        self.assertEqual(state["items"][1]["status"],"queued")
        self.assertEqual(batch.progress(state)["no_match"],0)
        self.assertEqual(state["searches_this_run"],1)

    def test_existing_subtitle_skips_without_provider_request(self):
        rows=batch.choose(self.rows,series="Example Show",picks=[(1,1)])
        state=batch.fresh_state(rows,batch.selector(series="Example Show",picks=[(1,1)]))
        with tempfile.TemporaryDirectory() as folder:
            media=Path(folder)/"video.mkv"
            media.write_bytes(b"offline-fixture")
            rows[0]["host_path"]=str(media)
            with patch.object(batch.stage,"japanese_sidecar_exists",return_value=True):
                batch.execute(rows,state,limit=20,
                              runner=lambda *a,**k:self.fail("provider request"),
                              writer=lambda doc:None)
        self.assertEqual(state["state"],"completed")
        self.assertEqual(batch.progress(state)["already_covered"],1)
        self.assertEqual(state["searches_this_run"],0)

    def test_private_job_state_is_atomic_owner_only_and_resumable(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);os.chmod(folder,0o700)
            state_path=folder/"job.json"
            rows=batch.choose(self.rows,series="Example Show")
            state=batch.fresh_state(rows,batch.selector(series="Example Show"))
            batch.write_state(state,state_path)
            self.assertEqual(state_path.stat().st_mode&0o777,0o600)
            self.assertEqual(batch.read_state(state_path)["selector"]["series"],
                             "Example Show")
            self.assertFalse(any(x.name.startswith(".subhub-jellyfin-job-")
                                 for x in folder.iterdir()))


class DashboardJellyfinControls(unittest.TestCase):
    def test_full_series_and_scoped_seasons_validation(self):
        self.assertEqual(dashboard.jellyfin_source_arguments(
            {"series":"It's Always Sunny in Philadelphia"})[:2],
            ["--series","It's Always Sunny in Philadelphia"])
        args=dashboard.jellyfin_source_arguments(
            {"series":"Example Show","seasons":[2,1]})
        self.assertEqual(args[-4:],["--season","1","--season","2"])
        picks=dashboard.jellyfin_source_arguments({"series":"Example Show",
            "picks":[{"season":2,"episode":3}]})
        self.assertIn("S02E003",picks)
        for req in [
            {"series":"Example Show","bad":3},
            {"series":"Example Show","seasons":[True]},
            {"series":"Example Show","picks":[{"season":1,"episode":False}]},
            {"series":"Example Show","picks":[{"season":1,"episode":1}]*2},
            {"series":"Example Show","seasons":[]},
        ]:
            with self.assertRaises(ValueError):
                dashboard.jellyfin_source_arguments(req)

    def test_background_start_previews_exact_scope_then_uses_systemd(self):
        calls=[]
        def run(command,**kwargs):
            calls.append(command)
            if len(calls)==1:
                return SimpleNamespace(returncode=0,stdout='{"eligible": 135}',stderr="")
            return SimpleNamespace(returncode=0,stdout="Running as unit...",stderr="")
        with patch.object(dashboard,"unit_active",return_value=False), \
             patch.object(dashboard,"translation_busy",return_value=False), \
             patch.object(dashboard,"JELLYFIN_SOURCE_EXEC",Path(__file__)), \
             patch.object(dashboard.subprocess,"run",side_effect=run):
            result=dashboard.start_jellyfin_source({"series":"Example Show"})
        self.assertEqual(result["eligible"],135)
        self.assertEqual(result["max_searches_this_run"],20)
        self.assertNotIn("--run",calls[0])
        self.assertIn("--run",calls[1])
        self.assertIn("--collect",calls[1])
        self.assertIn("KillMode=control-group"," ".join(calls[1]))
        self.assertNotIn("--start",calls[1])

    def test_status_is_exact_receipt_not_inferred_from_disabled_button(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);os.chmod(folder,0o700)
            path=folder/"job.json"
            rows=[tv("a"*32,1,1),tv("b"*32,1,2)]
            state=batch.fresh_state(rows,batch.selector(series="Example Show"))
            state["items"][0]["status"]="published"
            state["items"][1]["status"]="queued"
            state["state"]="paused"
            batch.write_state(state,path)
            with patch.object(dashboard,"JELLYFIN_SOURCE_STATE",path), \
                 patch.object(dashboard,"JELLYFIN_SOURCE_EXEC",Path(__file__)), \
                 patch.object(dashboard,"unit_active",return_value=False):
                data=dashboard.jellyfin_source_status()
            self.assertTrue(data["known"])
            self.assertEqual(data["total"],2)
            self.assertEqual(data["finished"],1)
            self.assertEqual(data["pending"],1)
            self.assertEqual(data["published"],1)
            self.assertEqual(data["state"],"paused")

    def test_dashboard_has_real_whole_series_and_progress_controls(self):
        html=(Path(__file__).parent/"tools/subhub_dashboard.html").read_text()
        for marker in ('id="source-whole-series"','id="jellyfin-job-meter"',
                       'id="jellyfin-job-continue"','id="jellyfin-job-stop"',
                       'renderJellyfinJob(d)','"/api/jellyfin-source/start"',
                       '"/api/jellyfin-source/stop"'):
            self.assertIn(marker,html)


if __name__=="__main__":
    unittest.main()
