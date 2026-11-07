"""Offline tests for loopback-only SubHub dashboard and guarded owner controls."""
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tools import subhub_dashboard_server as dashboard


def sample():
    return {
        "batch_id": "batch-example", "state": "running",
        "phase": "search_opensubtitles", "cycle": 2, "cycles": 12,
        "search_budget": 100, "phase_current": 37, "phase_total": 100,
        "last_item": "Venture Bros. S07E03",
        "counts": {"search_started": 137, "search_plausible": 20,
                   "search_review": 7, "search_none": 109,
                   "search_errors": 0, "staged": 29,
                   "published_new": 23, "held_titles": 6},
        "held_reasons": {"timing_alignment_failed": 6},
        "updated_utc": "2026-11-06T04:15:00+00:00",
    }


class StatusTests(unittest.TestCase):
    def test_snapshot_counts_are_real_not_candidate_publications(self):
        data = dashboard.snapshot(sample(), True, False, [])
        self.assertEqual(data["counts"]["published_new"], 23)
        self.assertEqual(data["counts"]["search_completed"], 136)
        self.assertEqual(data["counts"]["search_in_flight"], 1)
        self.assertEqual(data["search_progress"], {"current": 137, "total": 1200})
        self.assertEqual(data["cycle_done"], 1)
        self.assertEqual(data["translation"]["state"], "not_connected")
        self.assertFalse(data["controls"]["available"])

    def test_live_source_reads_real_cycle_progress_not_saved_manual_counts(self):
        events=[
            "RUNNING_SOURCES_ONLY_CYCLE search_budget=600 stage_budget=200 publish_limit=200",
            "=== DISCOVERY ===",
            "Search requests planned: 3 | budget: 600",
            "[1/3] SEARCHING: Family Guy S15E02",
            "[1/3] PLAUSIBLE: Family Guy S15E02",
            "[2/3] SEARCHING: American Dad! S20E03",
        ]
        payload="\n".join(json.dumps({
            "MESSAGE":message,"__REALTIME_TIMESTAMP":str(1794000000000000+i*1000000)
        }) for i,message in enumerate(events))
        result=dashboard.subprocess.CompletedProcess([],0,stdout=payload)
        with patch.object(dashboard.subprocess,"run",return_value=result), \
             patch.object(dashboard.time,"monotonic",return_value=2000.):
            old=dict(dashboard._SOURCE_CACHE)
            try:
                dashboard._SOURCE_CACHE.update(when=0.0,state=None)
                current=dashboard.scheduled_source_activity(True)
                self.assertEqual(current["search_planned"],3)
                self.assertEqual(current["search_completed"],1)
                self.assertTrue(current["metrics_available"])
                self.assertEqual(current["search_found"],1)
                self.assertEqual(current["search_none"],0)
                self.assertEqual(current["staged"],0)
                self.assertEqual(current["published"],0)
                self.assertIn("American Dad",current["current_item"])
                self.assertEqual(current["stage_attempts"],0)
                self.assertEqual(current["phase_label"],"Searching Japanese subtitle providers")
                self.assertEqual(current["last_event"],1794000005.)
            finally:
                dashboard._SOURCE_CACHE.update(old)

    def test_unavailable_journal_is_unknown_not_false_zero_success(self):
        failed=dashboard.subprocess.CompletedProcess([],1,stdout="")
        with patch.object(dashboard.subprocess,"run",return_value=failed), \
             patch.object(dashboard.time,"monotonic",return_value=3000.):
            old=dict(dashboard._SOURCE_CACHE)
            try:
                dashboard._SOURCE_CACHE.update(when=0.,state=None)
                data=dashboard.scheduled_source_activity(True)
                self.assertTrue(data["active"])
                self.assertFalse(data["metrics_available"])
                self.assertEqual(data["search_found"],0)
            finally:
                dashboard._SOURCE_CACHE.update(old)

    def test_page_prioritizes_current_run_and_removes_manual_batch_dropdown(self):
        html=dashboard.HTML.read_text(encoding="utf-8")
        for name in ("live-matches","live-downloaded","live-published",
                     "live-none","live-review","live-errors"):
            self.assertIn('id="'+name+'"',html)
        self.assertNotIn('id="manual-history"',html)
        self.assertNotIn('aria-label="Saved manual batch results"',html)
        self.assertNotIn('id="job"',html)
        self.assertIn('live.metrics_available',html)

    def test_inactive_source_without_history_returns_no_live_progress(self):
        # This MUST be independent of the install target's actual systemd
        # journal. Completed real sourcing runs are allowed to have counts.
        empty=dashboard.subprocess.CompletedProcess([],0,stdout="")
        with patch.object(dashboard.subprocess,"run",return_value=empty), \
             patch.object(dashboard.time,"monotonic",return_value=4100.):
            previous=dict(dashboard._SOURCE_CACHE)
            try:
                dashboard._SOURCE_CACHE.update(when=0.0,state=None)
                result=dashboard.scheduled_source_activity(False)
                self.assertFalse(result["active"])
                self.assertFalse(result["metrics_available"])
                self.assertEqual(result["search_completed"],0)
                self.assertEqual(result["current_item"],"")
            finally:
                dashboard._SOURCE_CACHE.update(previous)

    def test_inactive_source_retains_completed_counts_as_history_not_live(self):
        # Last completed cycle is useful history, not evidence that the
        # sourcing service is currently active.
        messages=[
            "RUNNING_SOURCES_ONLY_CYCLE search_budget=3 stage_budget=2 publish_limit=2",
            "=== DISCOVERY ===",
            "Search requests planned: 2 | budget: 3",
            "[1/2] NONE: plausible=0 review=0",
            "[2/2] PLAUSIBLE: plausible=1 review=0",
            "AUTOFILL_CYCLE_COMPLETE",
        ]
        payload="\n".join(json.dumps({
            "MESSAGE":msg, "__REALTIME_TIMESTAMP":str(1794000000000000+i*1000000)
        }) for i,msg in enumerate(messages))
        journal=dashboard.subprocess.CompletedProcess([],0,stdout=payload)
        with patch.object(dashboard.subprocess,"run",return_value=journal), \
             patch.object(dashboard.time,"monotonic",return_value=4100.):
            previous=dict(dashboard._SOURCE_CACHE)
            try:
                dashboard._SOURCE_CACHE.update(when=0.0,state=None)
                result=dashboard.scheduled_source_activity(False)
                self.assertFalse(result["active"])
                self.assertTrue(result["metrics_available"])
                self.assertEqual(result["phase"],"source_completed")
                self.assertEqual(result["search_completed"],2)
                self.assertEqual(result["search_found"],1)
                self.assertEqual(result["search_none"],1)
                combined=dashboard.live_source_snapshot(
                    dashboard.snapshot(None,False),result)
                self.assertFalse(combined["source_active"])
                self.assertEqual(combined["state"],"completed")
            finally:
                dashboard._SOURCE_CACHE.update(previous)

    def test_web_dashboard_shows_real_movie_cues_and_held_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            movie=root/"subhub-translation"/"ja-abcdef0123456789"
            movie.mkdir(parents=True,mode=0o700)
            video=root/"As Above, So Below (2014)"/"As.Above.So.Below.mp4"
            video.parent.mkdir()
            video.write_bytes(b"fake video")
            jid="d789e397319aad9a860633811b528b40"
            manifest=movie/"manifest.json"
            manifest.write_text(json.dumps({
                "jellyfin_id":jid,"video":str(video),"cue_count":1455}))
            manifest.chmod(0o600)
            with sqlite3.connect(movie/"progress.sqlite3") as db:
                db.execute("CREATE TABLE translation (idx INTEGER, id INTEGER, english TEXT, japanese TEXT, status TEXT, seconds REAL)")
                db.executemany("INSERT INTO translation VALUES (?,?,?,?,?,?)",
                    [(i-1,i,"Hello","こんにちは","translated",0.5)
                     for i in range(1,1300)] +
                    [(1299,929,"1, 2, 3, 4, 5, 6...","","held_translation",0.5)])
            with patch.object(dashboard,"_plamo_running_ids",return_value={jid}):
                jobs=dashboard.translation_jobs(
                    movie_root=movie.parent,
                    episode_root=root/"unused",
                    single_root=root/"nonexistent")
            self.assertEqual(len(jobs),1)
            item=jobs[0]
            self.assertEqual(item["state"],"translating")
            self.assertEqual(item["processed"],1300)
            self.assertEqual(item["translated"],1299)
            self.assertEqual(item["held"],1)
            self.assertEqual(item["held_details"][0]["cue"],929)
            self.assertIn("1, 2, 3",item["held_details"][0]["english"])
            self.assertAlmostEqual(item["percent"],89.3)
            self.assertFalse(item["published"])

    def test_stopped_movie_not_claimed_active_or_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            movie=root/"ja-a1"
            movie.mkdir(mode=0o700)
            video=root/"film.mp4"
            video.write_bytes(b"video")
            jid="d789e397319aad9a860633811b528b40"
            manifest=movie/"manifest.json"
            manifest.write_text(json.dumps({
                "jellyfin_id":jid,"video":str(video),"cue_count":5}))
            manifest.chmod(0o600)
            with sqlite3.connect(movie/"progress.sqlite3") as db:
                db.execute("CREATE TABLE translation (status TEXT,seconds REAL)")
                db.execute("INSERT INTO translation VALUES ('translated',1.0)")
            job=dashboard._plamo_checkpoint(movie,{
                "jellyfin_id":jid,"video":str(video),"cue_count":5},
                "movie",set(),False)
            self.assertEqual(job["state"],"needs_resume")
            self.assertFalse(job["published"])
            video.with_name(video.stem+".ja.PLaMo8B.srt").write_text(
                "1\n00:00:01,000 --> 00:00:02,000\nはい\n")
            published=dashboard._plamo_checkpoint(movie,{
                "jellyfin_id":jid,"video":str(video),"cue_count":5},
                "movie",set(),False)
            self.assertTrue(published["published"])

    def test_running_american_dad_episode_uses_verified_batch_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"S20E03"
            folder.mkdir(mode=0o700)
            video=root/"S20E03.mp4"
            video.write_bytes(b"video")
            meta={"video":str(video),"cue_count":440,"episode":"S20E03"}
            with sqlite3.connect(folder/"progress.sqlite3") as db:
                db.execute("CREATE TABLE translation (status TEXT, seconds REAL)")
                db.execute("INSERT INTO translation VALUES ('translated', 1.0)")
            active=dashboard._plamo_checkpoint(folder,meta,"episode",set(),"S20E03")
            stopped=dashboard._plamo_checkpoint(folder,meta,"episode",set(),"")
            self.assertTrue(active["active"])
            self.assertEqual(active["state"],"translating")
            self.assertFalse(stopped["active"])
            self.assertEqual(stopped["state"],"needs_resume")

    def test_batch_summary_reports_running_even_before_episode_selected(self):
        with patch.object(dashboard,"translation_jobs",return_value=[]), \
             patch.object(dashboard,"american_dad_batch_activity",return_value={
                 "active":True,"episode":"","pid":1234}):
            snap=dashboard.translation_snapshot()
        self.assertEqual(snap["state"],"active")
        self.assertEqual(snap["active_jobs"],0)
        self.assertTrue(snap["american_dad_batch"]["active"])

    def test_real_translation_contract_without_running_source_batch(self):
        with patch.object(dashboard,"translation_jobs",return_value=[{
            "state":"needs_resume","active":False,"published":False,
            "held":1,"title":"Example","processed":900,"total":1455}]):
            result=dashboard.translation_snapshot()
            self.assertEqual(result["engine"],"PLaMo 8B")
            self.assertEqual(result["held_cues"],1)
            self.assertEqual(result["active_jobs"],0)
            self.assertEqual(result["total_jobs"],1)

    def test_shutdown_marks_interruption_even_if_json_claims_running(self):
        data = dashboard.snapshot(sample(), False, False, [])
        self.assertEqual(data["state"], "interrupted")
        self.assertFalse(data["source_active"])

    def test_daily_source_service_is_distinct(self):
        data = dashboard.snapshot(sample(), False, True, [])
        self.assertEqual(data["state"], "scheduled_source_running")
        self.assertTrue(data["source_active"])

    def test_no_batch_idle_is_not_translator_ready(self):
        data = dashboard.snapshot({})
        self.assertEqual(data["state"], "idle")
        self.assertEqual(data["translation"]["state"], "not_connected")

    def test_publish_phase_progress_uses_media_lines_not_guesses(self):
        logs = [
            "=== PHASE sync_and_publish 2026-11-06T04:00:00Z ===",
            "=== UNIFIED JAPANESE SUBTITLE PUBLISH QUEUE ===",
            "Staged candidates: 9 | unique titles: 7 | max new sidecars: 10",
            "MEDIA: a | candidate IDs: 1",
            "MEDIA: b | candidate IDs: 2",
        ]
        doc = sample()
        doc["phase"] = "sync_and_publish"
        doc["phase_total"] = 0
        data = dashboard.snapshot(doc, True, False, logs)
        self.assertEqual(data["phase_progress"], {"current": 2, "total": 7})

    def test_publish_item_title_never_leaks_stale_staging_title(self):
        logs = [
            "=== PHASE stage_matched_japanese 2026-11-06T04:01:00Z ===",
            "[12/30] STAGING: Bowfinger (1999)",
            "=== PHASE sync_and_publish 2026-11-06T04:02:00Z ===",
            "=== UNIFIED JAPANESE SUBTITLE PUBLISH QUEUE ===",
            "Staged candidates: 29 | unique titles: 29 | max new sidecars: 30",
            "MEDIA: exampleid | candidate IDs: x",
        ]
        doc = sample()
        doc.update(phase="sync_and_publish",last_item="Bowfinger (1999)",phase_total=0)
        result = dashboard.snapshot(doc, True, False, logs)
        self.assertEqual(result["current_item"],
                         "Validating subtitle 1 / 29 (title not yet reported)")
        self.assertNotIn("Bowfinger", result["current_item"])
        logs.append("RESULT: The Shining (1980) | ready_ffsubsync")
        result = dashboard.snapshot(doc, True, False, logs)
        self.assertEqual(result["current_item"],
                         "Last evaluated: The Shining (1980) (item 1 / 29)")
        self.assertTrue(any("RESULT: The Shining" in line for line in result["events"]))
        logs.append("MEDIA: nextid | candidate IDs: y")
        result = dashboard.snapshot(doc, True, False, logs)
        self.assertIn("Validating subtitle 2 / 29", result["current_item"])
        self.assertNotIn("The Shining", result["current_item"])

    def test_phase_change_cannot_carry_last_publication_title(self):
        logs = [
            "=== PHASE sync_and_publish 2026-11-06T04:00:00Z ===",
            "MEDIA: first | candidate IDs: 1",
            "RESULT: Bowfinger (1999) | ready_ffsubsync",
            "=== PHASE search_opensubtitles 2026-11-06T04:04:00Z ===",
        ]
        doc = sample()
        doc.update(phase="sync_and_publish",last_item="Bowfinger (1999)",phase_total=0)
        self.assertNotIn("Bowfinger", dashboard.snapshot(doc, True, False, logs)["current_item"])

    def test_log_path_outside_private_directory_is_never_read(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "unsafe.log"
            p.write_text("secret", encoding="utf-8")
            self.assertIsNone(dashboard.trusted_log({"log": str(p)}))

    def test_state_file_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "safe.json"
            link = Path(temp) / "link.json"
            file.write_text("{}", encoding="utf-8")
            file.chmod(0o600)
            link.symlink_to(file)
            with self.assertRaises(RuntimeError):
                dashboard.checked_state(link)

    def test_activity_html_is_not_injected_by_backend(self):
        text = dashboard.safe_text("<script>alert(1)</script>\n", 80)
        # Status transport is plain JSON; the browser renders it via textContent.
        self.assertEqual(text, "<script>alert(1)</script> ")
        self.assertIn("textContent", dashboard.HTML.read_text(encoding="utf-8")
                      if dashboard.HTML.is_file() else
                      (Path(__file__).parent / "tools/subhub_dashboard.html").read_text(encoding="utf-8"))


class HTTPTests(unittest.TestCase):
    def test_activating_oneshot_source_is_busy(self):
        result = dashboard.subprocess.CompletedProcess([], 0, stdout="activating\n")
        with patch.object(dashboard.subprocess, "run", return_value=result):
            self.assertTrue(dashboard.unit_active(dashboard.SCHEDULED_UNIT))

    def test_unknown_service_state_blocks_controls(self):
        result = dashboard.subprocess.CompletedProcess([], 1, stdout="")
        with patch.object(dashboard.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "cannot_verify"):
                dashboard.control_availability()

    def test_scheduled_work_does_not_fake_manual_batch_as_running(self):
        saved = dashboard.snapshot(sample(), False, False, [])
        source = {"active": True, "phase": "running", "phase_label": "Sourcing",
                  "current_item": "Searching", "events": []}
        result = dashboard.live_source_snapshot(saved, source)
        self.assertEqual(result["state"], "scheduled_source_running")
        self.assertEqual(result["manual_batch_history"]["state"], "interrupted")
        self.assertTrue(result["source_active"])

    def test_auto_start_is_nonblocking_and_only_requests_existing_unit(self):
        with patch.object(dashboard, "unit_active", return_value=False):
            cp = dashboard.subprocess.CompletedProcess([], 0, stdout="ok")
            with patch.object(dashboard.subprocess, "run", return_value=cp) as run:
                result = dashboard.source_controls("start-auto")
        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.args[0], [
            "systemctl", "--user", "start", "--no-block",
            dashboard.SCHEDULED_UNIT])


    def test_control_availability_prevents_duplicate_workers(self):
        with patch.object(dashboard, "unit_active", side_effect=[False, True]):
            c = dashboard.control_availability()
        self.assertTrue(c["available"])
        self.assertFalse(c["start_auto"])
        self.assertTrue(c["stop_auto"])
        self.assertFalse(c["start_manual"])
        self.assertFalse(c["stop_manual"])

    def test_source_start_is_guarded_when_another_service_is_active(self):
        with patch.object(dashboard, "unit_active", side_effect=[False, True]):
            with patch.object(dashboard.subprocess, "run") as runner:
                with self.assertRaises(RuntimeError):
                    dashboard.source_controls("start-auto")
                runner.assert_not_called()

    def test_source_controls_refuse_competing_translation_batch(self):
        with patch.object(dashboard, "unit_active",
                          side_effect=[False, False, True]), \
             patch.object(dashboard.subprocess, "run") as runner:
            with self.assertRaisesRegex(RuntimeError,
                                        "translation_active_cannot_start_source"):
                dashboard.source_controls("start-auto")
            runner.assert_not_called()

    def test_source_first_translation_batch_uses_existing_worker_and_systemd(self):
        with patch.object(dashboard, "unit_active", return_value=False), \
             patch.object(dashboard, "american_dad_batch_activity",
                          return_value={"active":False}), \
             patch.object(dashboard, "_plamo_running_ids", return_value=set()), \
             patch.object(dashboard, "BATCH_EXEC", Path(dashboard.__file__)), \
             patch.object(dashboard.season_batch, "ENGINE",
                          Path(dashboard.season_batch.__file__)), \
             patch.object(dashboard.season_batch,"plan", return_value={
                 "ready":4,"blocked":2}), \
             patch.object(dashboard.subprocess,"run", return_value=
                          dashboard.subprocess.CompletedProcess([],0,stdout="ok")) as runner:
            result=dashboard.start_season_translation({
                "series":"It's Always Sunny in Philadelphia",
                "season":1,"count":20,"start":1})
        self.assertEqual(result["accepted"],4)
        argv=runner.call_args.args[0]
        self.assertEqual(argv[:2],["systemd-run","--user"])
        self.assertIn("--series",argv)
        self.assertIn("It's Always Sunny in Philadelphia",argv)
        self.assertEqual(argv[argv.index("--season")+1],"1")

    def test_batch_with_zero_source_first_ready_does_not_launch(self):
        with patch.object(dashboard, "unit_active", return_value=False), \
             patch.object(dashboard, "american_dad_batch_activity",
                          return_value={"active":False}), \
             patch.object(dashboard, "_plamo_running_ids", return_value=set()), \
             patch.object(dashboard, "BATCH_EXEC", Path(dashboard.__file__)), \
             patch.object(dashboard.season_batch, "ENGINE",
                          Path(dashboard.season_batch.__file__)), \
             patch.object(dashboard.season_batch,"plan",
                          return_value={"ready":0,"blocked":20}), \
             patch.object(dashboard.subprocess,"run") as runner:
            with self.assertRaisesRegex(RuntimeError,"no_source_first_eligible"):
                dashboard.start_season_translation({
                    "series":"It's Always Sunny in Philadelphia",
                    "season":1,"count":20,"start":1})
            runner.assert_not_called()


    def test_season_sources_start_is_explicitly_scoped_and_transient(self):
        selection={"series":"It's Always Sunny in Philadelphia","season":12}
        with patch.object(dashboard,"unit_active",return_value=False), \
             patch.object(dashboard,"translation_busy",return_value=False), \
             patch.object(dashboard,"season_sources_status",
                          return_value={"available":True}), \
             patch.object(dashboard.season_sources,"scope",return_value={
                 "eligible":10,"ids":{"a"*32:"/media/season12.mkv"}}), \
             patch.object(dashboard.subprocess,"run",return_value=
                          dashboard.subprocess.CompletedProcess([],0,stdout="ok")) as subprocess_run:
            result=dashboard.start_season_sources(selection)
        self.assertEqual(result["accepted"],10)
        command=subprocess_run.call_args.args[0]
        self.assertEqual(command[:2],["systemd-run","--user"])
        self.assertIn("--season",command)
        self.assertEqual(command[command.index("--season")+1],"12")

    def test_season_source_refused_during_other_work(self):
        request={"series":"It's Always Sunny in Philadelphia","season":12}
        with patch.object(dashboard,"unit_active",side_effect=[False,True]), \
             patch.object(dashboard.subprocess,"run") as runner:
            with self.assertRaisesRegex(RuntimeError,"another_source"):
                dashboard.start_season_sources(request)
            runner.assert_not_called()

    def test_season_source_start_refuses_no_work(self):
        selection={"series":"It's Always Sunny in Philadelphia","season":12}
        with patch.object(dashboard,"unit_active",return_value=False), \
             patch.object(dashboard,"translation_busy",return_value=False), \
             patch.object(dashboard,"season_sources_status",
                          return_value={"available":True}), \
             patch.object(dashboard.season_sources,"scope",
                          return_value={"eligible":0,"ids":{}}), \
             patch.object(dashboard.subprocess,"run") as runner:
            with self.assertRaisesRegex(RuntimeError,"no_pending_japanese"):
                dashboard.start_season_sources(selection)
            runner.assert_not_called()

    def test_dashboard_controls_are_present_in_html(self):
        source = dashboard.HTML.read_text(encoding="utf-8")
        for action in ("start-auto","stop-auto","start-manual","stop-manual"):
            self.assertIn('id="action-' + action + '"', source)
        self.assertIn("X-Subhub-Token", source)
        for identifier in ("translation-series","translation-season",
                           "translation-count","translation-preview-button",
                           "translation-start-button","translation-stop-button",
                            "season-source-button","season-source-stop-button"):
            self.assertIn('id="' + identifier + '"', source)
        self.assertIn("Review ", source)

    def test_owner_http_and_no_remote_listener(self):
        with patch.object(dashboard, "status_payload",
                          return_value=dashboard.snapshot(sample(), True)):
            server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertEqual(server.server_address[0], "127.0.0.1")
                base = "http://127.0.0.1:" + str(server.server_address[1])
                with urlopen(base + "/api/status", timeout=3) as response:
                    body = json.load(response)
                    self.assertEqual(body["counts"]["published_new"], 23)
                    self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                with urlopen(base + "/healthz", timeout=3) as response:
                    self.assertEqual(json.load(response)["mode"], "owner_controls")
                with urlopen(base + "/api/owner-token", timeout=3) as response:
                    token = json.load(response)["token"]
                self.assertEqual(token, dashboard.OWNER_TOKEN)
                control = Request(
                    base + "/api/control/start-auto", data=b"{}",
                    headers={"Content-Type":"application/json",
                             "X-Subhub-Token":token,
                             "Origin":base},
                    method="POST")
                with patch.object(dashboard, "source_controls",
                                  return_value={"ok":True,"action":"start-auto"}) as action:
                    with urlopen(control, timeout=3) as response:
                        self.assertTrue(json.load(response)["ok"])
                    action.assert_called_once_with("start-auto")
                selection = {"series":"It's Always Sunny in Philadelphia",
                             "season":1,"count":20,"start":1}
                batch_req = Request(
                    base+"/api/translation/start",
                    data=json.dumps(selection).encode("utf-8"),
                    headers={"Content-Type":"application/json",
                             "X-Subhub-Token":token,"Origin":base},
                    method="POST")
                with patch.object(dashboard,"start_season_translation",
                    return_value={"ok":True,"accepted":3}) as batch_start:
                    with urlopen(batch_req,timeout=3) as response:
                        self.assertEqual(json.load(response)["accepted"],3)
                    batch_start.assert_called_once_with(selection)
                forbidden = Request(
                    base + "/api/control/start-auto", data=b"{}",
                    headers={"Content-Type":"application/json",
                             "X-Subhub-Token":token,
                             "Origin":"http://evil.example"},
                    method="POST")
                with self.assertRaises(HTTPError) as denied:
                    urlopen(forbidden, timeout=3)
                self.assertEqual(denied.exception.code,403)
                req = Request(base + "/api/status", data=b"{}", method="POST")
                with self.assertRaises(HTTPError) as result:
                    urlopen(req, timeout=3)
                self.assertEqual(result.exception.code, 405)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)


if __name__ == "__main__":
    unittest.main()
