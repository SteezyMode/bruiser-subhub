"""Regression tests for private library-wide saved-review inspection."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import subhub_review_trials as review


def movie(jid="a"*32, title="Recovered Horror"):
    return {
        "jellyfin_id": jid, "kind": "Movie", "title": title, "year": 1985,
        "status": "ready_ja_search",
        "host_path": "/mnt/2TB/Plex Expansion/Movies/Horror/"+title+".mkv",
    }


def episode(jid="b"*32):
    return {"jellyfin_id":jid,"kind":"Episode","series_title":"Example Show",
            "season":3,"episode":8,"status":"ready_ja_search",
            "host_path":"/mnt/2TB/Plex Expansion/Television/Example/Season 03/S03E08.mkv"}


def hit(provider="subdl",remote="12345-340891",language="ja"):
    return {"provider":provider,"subtitle_id":remote,"language":language,
            "grade":"review","filename":"opaque.zip"}


class ReviewTrialTests(unittest.TestCase):
    def test_movie_review_selection_skips_episodes_and_unknown_titles(self):
        m=movie()
        e=episode()
        docs={
            m["jellyfin_id"]:{"candidates":[
                hit(), hit(), hit("opensubtitles","1234567"),
                hit("subf2m","junk"), hit("subdl","2222-123456","en")]},
            e["jellyfin_id"]:{"candidates":[hit("opensubtitles","9876543")]}
        }
        jobs,counts=review.audit_candidates(
            [m,e,dict(movie("c"*32),status="existing_japanese_subtitle")],
            reader=lambda jid:docs.get(jid))
        self.assertEqual(len(jobs),2)
        self.assertEqual({r["kind"] for r,_ in jobs},{"Movie"})
        self.assertEqual(counts["saved_review_hits"],5)
        self.assertEqual(counts["other_provider_review_hits"],1)
        self.assertEqual(counts["invalid_or_nonja_review_hits"],1)
        self.assertEqual(counts["duplicate_saved_hit"],1)
        self.assertEqual(counts["eligible_subdl"],1)
        self.assertEqual(counts["eligible_opensubtitles"],1)
        no_tv,_=review.audit_candidates(
            [e],reader=lambda jid:docs.get(jid))
        self.assertEqual(no_tv,[])

    def test_review_selection_rejects_forced_and_invalid_provider_id(self):
        row=movie()
        bad=[
            dict(hit(),forced=True),
            dict(hit(),kind="forced"),
            hit("subdl","bad slash",language="ja"),
            hit("opensubtitles","not-numeric",language="ja"),
            hit("subdl","11111-2222",language="en"),
            dict(hit(),grade="plausible"),
        ]
        jobs,_=review.audit_candidates(
            [row],reader=lambda _:{"candidates":bad})
        self.assertEqual(jobs,[])

    def test_subdl_trial_records_success_without_publisher_or_stage_db(self):
        row=movie()
        candidate=hit()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            path=root/"native-archive.zip"
            provider=Mock(return_value=b"ZIP bytes from provider")
            with patch.object(review,"QUARANTINE",root), \
                 patch.object(review.stage,"private_root"), \
                 patch.object(review.stage,"duration_if_safe",return_value=5800), \
                 patch.object(review.subdl,"cached_zip_path",return_value=path), \
                 patch.object(review.subdl,"identity_ok",return_value=False), \
                 patch.object(review,"inspect_subdl",return_value=(
                     "1\\n00:00:01,000 --> 00:00:02,000\\nこんにちは\\n".encode("utf-8"),
                     {"cues":908,"japanese_characters":6195},{})), \
                 patch.object(review,"trial_alignment",return_value={
                     "alignment_reference":"same_video_embedded_english",
                     "timing_shift_range_seconds":[1.877,1.877]}), \
                 patch.object(review.stage,"stage_db") as stage_db, \
                 patch.object(review.publisher,"publish") as publish:
                origin,result=review.trial(row,candidate,download_subdl=provider)
                self.assertEqual(origin,"downloaded")
                self.assertEqual(result["status"],
                                 "timing_trial_pass_identity_unverified")
                self.assertFalse(result["metadata_identity_verified"])
                stage_db.assert_not_called()
                publish.assert_not_called()
                _,receipt=review.key_path(row,candidate)
                saved=json.loads(receipt.read_text("utf-8"))
                self.assertEqual(saved["source_sha256"],
                    review.hashlib.sha256(b"ZIP bytes from provider").hexdigest())
                self.assertEqual(saved["status"],
                                 "timing_trial_pass_identity_unverified")
                self.assertNotIn("source_content",saved)

    def test_invalid_opensubtitles_bytes_are_cached_and_never_downloaded_twice(self):
        row=movie()
        candidate=hit("opensubtitles","9876543")
        download=Mock(return_value=b"garbled but nonempty caption file")
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(review,"QUARANTINE",root), \
                 patch.object(review.stage,"private_root"), \
                 patch.object(review.stage,"duration_if_safe",return_value=5800), \
                 patch.object(review.stage,"identity_ok",return_value=False), \
                 patch.object(review.stage,"stage_db") as stage_db, \
                 patch.object(review,"trial_alignment") as alass:
                a,r1=review.trial(row,candidate,download_os=download)
                b,r2=review.trial(row,candidate,download_os=download)
                self.assertEqual((a,b),("downloaded","cached"))
                self.assertEqual(r1["status"],"held_source_or_structure")
                self.assertEqual(r2["status"],"held_source_or_structure")
                self.assertEqual(download.call_count,1)
                stage_db.assert_not_called()
                alass.assert_not_called()
                _,receipt=review.key_path(row,candidate)
                self.assertEqual(json.loads(receipt.read_text())["status"],
                                 "held_source_or_structure")

    def test_unchanged_receipt_skips_repeated_trial_but_changed_bytes_do_not(self):
        row=movie()
        c=hit("opensubtitles","9876543")
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(review,"QUARANTINE",root), \
                 patch.object(review.stage,"private_root"):
                data=b"saved undecodable japanese bytes"
                raw,receipt=review.key_path(row,c)
                review.cache_raw(raw,data)
                review.cache_receipt(receipt,row,c,
                                     review.hashlib.sha256(data).hexdigest(),
                                     {"status":"held_source_or_structure",
                                      "reason":"staged_srt_block_malformed"})
                self.assertTrue(review.already_inspected(row,c))
                raw.unlink()
                review.cache_raw(raw,b"changed release bytes")
                self.assertFalse(review.already_inspected(row,c))
                raw.unlink()
                self.assertFalse(review.already_inspected(row,c))
                self.assertEqual(review.TRIAL_GATE_VERSION,"1")

    def test_apply_advances_past_previously_inspected_movie(self):
        first=movie("a"*32,"Alpha Film")
        second=movie("b"*32,"Beta Film")
        with tempfile.TemporaryDirectory() as folder:
            import os
            fd=os.open(str(Path(folder)/"lock"),os.O_CREAT|os.O_RDWR,0o600)
            with patch.object(review.saved,"check_idle"), \
                 patch.object(review.saved.autofill,"lock",return_value=fd), \
                 patch.object(review.stage,"read_inventory",
                    return_value={row["jellyfin_id"]:row for row in (first,second)}), \
                 patch.object(review,"audit_candidates",return_value=(
                    [(first,hit("subdl","1-1111")),
                     (second,hit("subdl","2-2222"))],{"candidate_jobs":2})), \
                 patch.object(review.stage,"japanese_sidecar_exists",return_value=False), \
                 patch.object(review,"already_inspected",
                              side_effect=[True,False]), \
                 patch.object(review,"trial",return_value=("cached",{
                    "status":"timing_trial_held","cues":100,
                    "japanese_characters":1000})) as trial:
                self.assertEqual(review.run(SimpleNamespace(
                    provider="both",limit=1,apply=True,retry=False,
                    download_only=False,process_cache=False)),0)
                self.assertEqual(trial.call_count,1)
                self.assertEqual(trial.call_args.args[0]["title"],"Beta Film")

    def test_default_preview_calls_neither_provider_nor_publisher(self):
        row=movie()
        with tempfile.TemporaryDirectory() as folder:
            import os
            fd=os.open(str(Path(folder)/"lock"),os.O_CREAT|os.O_RDWR,0o600)
            with patch.object(review.saved,"check_idle"), \
                 patch.object(review.saved.autofill,"lock",return_value=fd), \
                 patch.object(review.stage,"read_inventory",
                              return_value={row["jellyfin_id"]:row}), \
                 patch.object(review,"audit_candidates",return_value=(
                     [(row,hit())],{"candidate_jobs":1})), \
                 patch.object(review,"trial") as trial:
                rc=review.run(SimpleNamespace(
                    provider="both",limit=6,apply=False,
                    download_only=False,process_cache=False))
                self.assertEqual(rc,0)
                trial.assert_not_called()

    def test_private_download_pass_caches_without_alass_or_publisher(self):
        row=movie()
        candidate=hit("opensubtitles","9876543")
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            data="1\\n00:00:01,000 --> 00:00:03,000\\nこんにちは\\n".encode()
            fetch=Mock(return_value=(data,"downloaded"))
            with patch.object(review,"QUARANTINE",root), \
                 patch.object(review.stage,"private_root"), \
                 patch.object(review.stage,"duration_if_safe",return_value=5400), \
                 patch.object(review,"trial_alignment") as alass, \
                 patch.object(review,"trial") as trial, \
                 patch.object(review.publisher,"preflight") as pub:
                origin,n=review.download_to_private_cache(
                    row,candidate,download_os=fetch)
                self.assertEqual((origin,n),("downloaded",len(data)))
                origin2,n2=review.download_to_private_cache(
                    row,candidate,download_os=fetch)
                self.assertEqual((origin2,n2),("cached",len(data)))
                self.assertEqual(fetch.call_count,1)
                alass.assert_not_called()
                trial.assert_not_called()
                pub.assert_not_called()

    def test_process_cache_never_calls_provider_even_when_missing(self):
        row=movie()
        candidate=hit("opensubtitles","9876543")
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(review,"QUARANTINE",Path(folder)), \
                 patch.object(review.stage,"private_root"), \
                 patch.object(review.stage,"duration_if_safe",return_value=5400):
                self.assertFalse(review.private_bytes_present(row,candidate))
                with self.assertRaisesRegex(RuntimeError,"review_source_not_cached"):
                    review.trial(row,candidate,download_subdl=review.cached_subdl_only,
                                 download_os=review.cached_opensubtitles_only)

    def test_new_worker_returns_existing_stage_bytes_without_new_get(self):
        code=review.stage.WORKER
        marker=code.index('"source":"existing_private_container_stage"')
        download=code.index("raw = provider.download(candidate)")
        self.assertLess(marker,download)
        self.assertIn('"new_download":False',code[:marker])

    def test_opensubtitles_transport_can_only_return_bytes_before_staging(self):
        worker=review.stage.WORKER
        self.assertIn('if job.get("trial_only") is True:',worker)
        self.assertIn('"result":"private_trial_bytes"',worker)
        # The first trial-only branch reuses cached staged bytes; the
        # SECOND branch safely returns newly downloaded bytes before staging.
        after_get=worker.index('if job.get("trial_only") is True:',
                               worker.index("raw = provider.download(candidate)"))
        self.assertLess(worker.index("raw = provider.download(candidate)"),
                        after_get)
        self.assertLess(after_get,worker.index("metrics = analyze(raw, runtime"))
        self.assertLess(after_get,worker.index("STAGE.mkdir(mode=0o700)"))


if __name__=="__main__":
    unittest.main()
