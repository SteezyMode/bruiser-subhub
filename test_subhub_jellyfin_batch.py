"""Offline regression for reusable Jellyfin-native series/movie source controls.

No provider calls, no real systemd services, no media/DB changes.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
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

    def test_live_source_worker_exposes_milestones_before_completion(self):
        code=("import sys,time;"
              "print('MEDIA: video ready',flush=True);"
              "print('JELLYFIN_JA_SEARCH_REQUEST: x',flush=True);"
              "time.sleep(.15);"
              "print('JELLYFIN_JA_MATCHING_CANDIDATES: 1',flush=True);"
              "time.sleep(.15);"
              "print('JELLYFIN_JA_BYTES: 100',flush=True)")
        events=[]
        rc,out,err=batch.call([sys.executable,"-u","-c",code],
                              timeout=5,progress=lambda phase,detail:events.append(phase))
        self.assertEqual(rc,0,err)
        self.assertIn("searching_provider",events)
        self.assertIn("matching",events)
        self.assertIn("download_received",events)
        self.assertIn("JELLYFIN_JA_BYTES:",out)
        self.assertEqual(err,"")

    def test_streamed_source_worker_honors_timeout(self):
        code="import time;time.sleep(2)"
        with self.assertRaises(subprocess.TimeoutExpired):
            batch.call([sys.executable,"-u","-c",code],timeout=.15)

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
        self.assertEqual((state["pass_processed"],state["pass_total"]),(1,3))
        second=batch.fresh_state(rows,selection,state,now=now+1)
        self.assertEqual((second["pass_processed"],second["pass_total"]),(0,2))
        self.assertEqual(second["items"][0]["status"],"no_match")
        self.assertEqual(second["items"][1]["status"],"queued")
        with patch.object(batch.stage,"japanese_sidecar_exists",return_value=False), \
             patch.object(batch.time,"sleep"):
            batch.execute(rows,second,limit=1,runner=runner,writer=lambda doc:None)
        self.assertEqual(len(calls),2)
        self.assertEqual(second["searches_this_run"],1)
        self.assertEqual((second["pass_processed"],second["pass_total"]),(1,2))
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
        self.assertEqual((state["pass_processed"],state["pass_total"]),(1,3))

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
        self.assertEqual((state["pass_processed"],state["pass_total"]),(1,1))

    def test_three_independent_media_holds_do_not_stop_series(self):
        rows=batch.choose(self.rows,series="Example Show")
        state=batch.fresh_state(rows,batch.selector(series="Example Show"))
        failures=[
            (1,"","RuntimeError: media_duration_unavailable"),
            (1,"MEDIA: S01E02 | runtime_seconds: 123\n",
             "RuntimeError: embedded_subtitle_check_failed"),
            (1,"JELLYFIN_JA_SEARCH_REQUEST: item\nJELLYFIN_JA_BYTES: bytes",
             "RuntimeError: japanese_subtitle_readability_failed"),
        ]
        calls=[]
        def runner(cmd,*,timeout):
            calls.append(cmd)
            return failures[len(calls)-1]
        with patch.object(batch.time,"sleep"):
            batch.execute(rows,state,limit=10,runner=runner,writer=lambda doc:None)
        self.assertEqual(len(calls),3)
        self.assertEqual(state["state"],"completed")
        self.assertEqual(batch.progress(state)["held"],3)
        self.assertEqual(state["searches_this_run"],1)
        self.assertEqual(state["items"][0]["reason"],"media_duration_unavailable")
        self.assertEqual(state["items"][2]["reason"],
                         "japanese_subtitle_readability_failed")

    def test_http_500_episodes_are_set_aside_and_queue_keeps_running(self):
        # A few bad episodes (or Jellyfin plugin 500s) do not block the rest.
        rows=batch.choose(self.rows,series="Example Show")
        rows.append(tv("9"*32,3,1))
        state=batch.fresh_state(rows,batch.selector(series="Example Show"))
        attempts=[]
        def runner(cmd,*,timeout):
            attempts.append(cmd)
            if len(attempts)<=3:
                return (1,"JELLYFIN_JA_SEARCH_REQUEST: item",
                        "HTTP Error 500: Internal Server Error")
            return (0,"JELLYFIN_JA_SEARCH_REQUEST: item\\n"
                      "HELD: no exactly matching Japanese SRT","")
        with patch.object(batch.time,"sleep"):
            batch.execute(rows,state,limit=20,runner=runner,writer=lambda doc:None)
        self.assertEqual(len(attempts),4)
        self.assertEqual(state["state"],"completed")
        self.assertEqual(state["searches_this_run"],4)
        self.assertEqual((state["pass_processed"],state["pass_total"]),(4,4))
        self.assertEqual([x["reason"] for x in state["items"][:3]],
                         ["provider_http_500"]*3)
        self.assertEqual(state["items"][3]["status"],"no_match")
        self.assertEqual(batch.progress(state)["pending"],0)
        # Next pass has no pending work. Existing holds remain reviewable,
        # not silently re-requested.
        next_pass=batch.fresh_state(rows,state["selector"],state,now=int(time.time())+1)
        self.assertEqual(next_pass["pass_total"],0)
        self.assertEqual(next_pass["pass_processed"],0)

    def test_separate_episode_resume_does_not_erase_whole_series_job(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);os.chmod(folder,0o700)
            with patch.object(batch,"STATE",folder/"current.json"):
                series_plan=batch.selector(series="Example Show")
                series_rows=batch.choose(self.rows,series="Example Show")
                prior=batch.fresh_state(series_rows,series_plan)
                prior["items"][0]["status"]="held"
                prior["items"][0]["reason"]="source_validation_hold"
                batch.write_job_state(prior)
                episode_plan=batch.selector(series="Example Show",picks=[(1,2)])
                ep=batch.fresh_state([series_rows[1]],episode_plan)
                ep["items"][0]["status"]="published"
                batch.write_job_state(ep)
                self.assertEqual(batch.read_state()["selector"],episode_plan)
                restored=batch.read_scoped_state(series_plan)
                self.assertEqual(restored["items"][0]["reason"],
                                 "source_validation_hold")
                self.assertEqual(len(restored["items"]),3)
                self.assertEqual(len(list(folder.glob("jellyfin-source-scope-*.json"))),2)

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
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        os.chmod(self.root,0o700)
        patcher=patch.object(dashboard,"JELLYFIN_SOURCE_LAUNCH",
                            self.root/"source-launch.json")
        patcher.start()
        self.addCleanup(patcher.stop)

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
        self.assertEqual(result["max_searches_this_run"],200)
        self.assertIn("--max-searches",calls[0])
        self.assertIn("200",calls[1])
        self.assertNotIn("--run",calls[0])
        self.assertIn("--run",calls[1])
        self.assertIn("--collect",calls[1])
        self.assertIn("KillMode=control-group"," ".join(calls[1]))
        self.assertNotIn("--start",calls[1])

    def test_selected_season_uses_20_searches_but_whole_series_uses_200(self):
        calls=[]
        def run(command,**kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0,stdout='{"eligible": 12}',stderr="")
        with patch.object(dashboard,"unit_active",return_value=False), \
             patch.object(dashboard,"translation_busy",return_value=False), \
             patch.object(dashboard,"JELLYFIN_SOURCE_EXEC",Path(__file__)), \
             patch.object(dashboard.subprocess,"run",side_effect=run):
            result=dashboard.start_jellyfin_source(
                {"series":"Example Show","seasons":[1]})
        self.assertEqual(result["max_searches_this_run"],20)
        self.assertEqual(calls[1][calls[1].index("--max-searches")+1],"20")

    def test_read_only_progress_folder_prevents_launch_before_systemd(self):
        calls=[]
        def run(command,**kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0,stdout='{"eligible": 78}',stderr="")
        with patch.object(dashboard,"unit_active",return_value=False), \
             patch.object(dashboard,"translation_busy",return_value=False), \
             patch.object(dashboard,"JELLYFIN_SOURCE_EXEC",Path(__file__)), \
             patch.object(dashboard,"write_jellyfin_launch",
                          side_effect=OSError(30,"Read-only file system")), \
             patch.object(dashboard.subprocess,"run",side_effect=run):
            with self.assertRaises(OSError):
                dashboard.start_jellyfin_source({"series":"Example Show"})
        # One read-only offline preview, ZERO systemd-run calls.
        self.assertEqual(len(calls),1)
        self.assertNotIn("systemd-run",calls[0])

    def test_failed_systemd_start_keeps_explicit_failure_receipt(self):
        calls=[]
        def run(command,**kwargs):
            calls.append(command)
            if len(calls)==1:
                return SimpleNamespace(returncode=0,stdout='{"eligible": 78}',stderr="")
            return SimpleNamespace(returncode=1,stdout="",stderr="unit refused")
        with patch.object(dashboard,"unit_active",return_value=False), \
             patch.object(dashboard,"translation_busy",return_value=False), \
             patch.object(dashboard,"JELLYFIN_SOURCE_EXEC",Path(__file__)), \
             patch.object(dashboard.subprocess,"run",side_effect=run):
            with self.assertRaisesRegex(RuntimeError,"Jellyfin_source_start_failed"):
                dashboard.start_jellyfin_source({"series":"Example Show"})
        self.assertEqual(len(calls),2)
        receipt=json.loads(dashboard.JELLYFIN_SOURCE_LAUNCH.read_text())
        self.assertEqual(receipt["state"],"launch_failed")
        self.assertEqual(len(receipt["job_id"]),16)
        with patch.object(dashboard,"unit_active",return_value=False), \
             patch.object(dashboard,"JELLYFIN_SOURCE_STATE",
                          self.root/"missing.json"):
            status=dashboard.jellyfin_source_status()
        self.assertEqual(status["state"],"launch_failed")
        self.assertIn("unit refused",status["current"])

    def test_live_health_probe_checks_mount_writability_not_just_mode(self):
        self.assertTrue(dashboard.jellyfin_job_receipts_writable())
        with patch.object(dashboard,"JELLYFIN_SOURCE_LAUNCH",
                          self.root/"missing"/"receipt.json"):
            self.assertFalse(dashboard.jellyfin_job_receipts_writable())

    def test_existing_dashboard_unit_preserves_home_read_only_except_receipts(self):
        root=Path(__file__).parent/"tools"
        unit=(root/"install_subhub_dashboard.sh").read_text()
        installer=(root/"install_global_ja_sourcing.py").read_text()
        for config in (unit,installer):
            self.assertIn("ReadWritePaths=%h/bruiser-pilot/ja-first-inventory",
                          config)
        self.assertIn("ProtectHome=read-only",unit)
        self.assertIn("ProtectSystem=strict",unit)
        self.assertIn("DASH_OVERRIDE",installer)
        self.assertIn("systemctl(\"daemon-reload\")",installer)

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

    def test_accepted_job_shows_before_any_progress_is_written(self):
        receipt={"schema":"jellyfin-source-launch-v1",
                 "job_id":"1"*16,"selector":{"series":"Example Show",
                 "seasons":[],"picks":[]},"eligible":78,"search_cap":200,
                 "accepted_at":int(time.time())}
        dashboard.write_jellyfin_launch(receipt)
        with patch.object(dashboard,"JELLYFIN_SOURCE_STATE",
                          self.root/"missing-progress.json"), \
             patch.object(dashboard,"JELLYFIN_SOURCE_EXEC",Path(__file__)), \
             patch.object(dashboard,"unit_active",return_value=True):
            info=dashboard.jellyfin_source_status()
        self.assertTrue(info["known"])
        self.assertTrue(info["active"])
        self.assertEqual(info["state"],"starting")
        self.assertEqual(info["pending"],78)
        self.assertIn("first progress checkpoint",info["current"])

    def test_old_progress_cannot_disguise_failed_new_job(self):
        launch={"schema":"jellyfin-source-launch-v1",
                "job_id":"2"*16,"selector":{"series":"Example Show",
                "seasons":[],"picks":[]},"eligible":78,"search_cap":200,
                "accepted_at":int(time.time())-30}
        dashboard.write_jellyfin_launch(launch)
        history=batch.fresh_state([tv("a"*32,1,1)],
                                  batch.selector(series="Old Show"))
        history["job_id"]="1"*16
        progress_file=self.root/"old-progress.json"
        batch.write_state(history,progress_file)
        with patch.object(dashboard,"JELLYFIN_SOURCE_STATE",progress_file), \
             patch.object(dashboard,"unit_active",return_value=False), \
             patch.object(dashboard,"_jellyfin_early_error",
                          return_value="JELLYFIN_BATCH_HELD RuntimeError existing_worker_lock"):
            info=dashboard.jellyfin_source_status()
        self.assertTrue(info["known"])
        self.assertEqual(info["state"],"failed_before_progress")
        self.assertFalse(info["progress_available"])
        self.assertEqual(info["total"],78)
        self.assertIn("existing_worker_lock",info["current"])

    def test_dashboard_javascript_parses_where_node_available(self):
        node=shutil.which("node")
        if not node:
            self.skipTest("Node.js syntax checker unavailable")
        html=(Path(__file__).parent/"tools/subhub_dashboard.html").read_text()
        script=html.split("<script>",1)[1].split("</script>",1)[0]
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/"dashboard.js"
            file.write_text(script,encoding="utf-8")
            proc=subprocess.run([node,"--check",str(file)],
                                capture_output=True,text=True,timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr[:500])

    def test_dashboard_has_real_whole_series_and_progress_controls(self):
        html=(Path(__file__).parent/"tools/subhub_dashboard.html").read_text()
        for marker in ('id="source-whole-series"','id="jellyfin-job-meter"',
                       'id="jellyfin-job-continue"','id="jellyfin-job-stop"',
                       'renderJellyfinJob(d)','"/api/jellyfin-source/start"',
                       '"/api/jellyfin-source/stop"'):
            self.assertIn(marker,html)


if __name__=="__main__":
    unittest.main()
