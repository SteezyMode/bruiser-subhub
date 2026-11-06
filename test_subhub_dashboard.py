"""Offline tests for standalone, read-only SubHub dashboard."""
import json
import os
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
    def test_readonly_http_and_no_remote_listener(self):
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
                    self.assertEqual(json.load(response)["mode"], "read_only")
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
