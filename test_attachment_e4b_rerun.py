"""Offline tests for fresh Attachment E4B retranslation, safe alternate publish and review.

Uses only disposable temp SQLite and fake local files. Never loads Ollama.
"""
from pathlib import Path
import io
import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import retranslate_attachment_e4b as run


def sample(n=3):
    chunks = []
    for i in range(1, n+1):
        chunks.append(
            f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\n"
            f"English cue {i}."
        )
    return ("\n\n".join(chunks)+"\n").encode("utf-8")


class AttachmentRerunTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.old = self.tmp / "main-state"
        self.new = self.tmp / "rerun-state"
        self.video = self.tmp / "Attachment (2022).mkv"
        self.video.write_bytes(b"mock video not actual media")
        self.original_ja = self.video.with_name(
            self.video.stem + ".Bruiser Japanese.ja.srt")
        self.original_ja.write_bytes(b"Original generic JA - do not modify.")
        self.original_bytes = self.original_ja.read_bytes()
        source = sample()
        st = service.Store(self.old)
        st.add(run.OLD_JOB_ID, self.video, source, "eng")
        st.state(run.OLD_JOB_ID, "published")
        st.cn.close()
        self.patchers = [
            patch.object(run, "OLD_ROOT", self.old),
            patch.object(run, "ROOT", self.new),
            patch.object(run, "EXPECTED_CUES", 3),
            patch.object(run, "REVIEW_ARCHIVE",
                         self.new/"review"/"Attachment-2022-E4B-review.tar.gz"),
            patch.object(run, "REVIEW_JA",
                         self.new/"review"/"Attachment-2022-E4B.ja.srt"),
            patch.object(service, "secure_video", return_value=None),
            patch.object(service, "audio_language", return_value="eng"),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def prepare(self):
        info = run.source_record()
        run.ensure_job(info)
        return info

    def fill(self, info):
        st = service.Store(self.new)
        st.record_japanese(info["job_id"],
                           {str(i):f"訳文{i}。" for i in range(1,4)})
        st.state(info["job_id"], "translated")
        return st

    def test_exact_original_english_is_staged_in_isolated_db(self):
        info = self.prepare()
        with sqlite3.connect(self.new/"jobs.sqlite3") as cn:
            job = cn.execute("SELECT video,source_cues,source_path FROM jobs"
                             ).fetchone()
            self.assertEqual(job[0], str(self.video))
            self.assertEqual(job[1], 3)
            self.assertEqual(Path(job[2]).read_bytes(), sample())
            self.assertEqual(cn.execute("SELECT count(*) FROM cues").fetchone()[0],3)
        with sqlite3.connect(self.old/"jobs.sqlite3") as cn:
            original = cn.execute("SELECT status FROM jobs").fetchone()
            self.assertEqual(original[0], "published")
        self.assertEqual(self.original_ja.read_bytes(), self.original_bytes)

    def test_produces_separate_review_track_and_private_english_ja_archive(self):
        info = self.prepare()
        st = self.fill(info)
        try:
            track = run.export_review(st, info)
            self.assertEqual(track.name,
                             self.video.stem + run.REVIEW_TRACK_SUFFIX)
            self.assertEqual(self.original_ja.read_bytes(), self.original_bytes)
            self.assertIn(b"\xe8\xa8\xb3\xe6\x96\x871", track.read_bytes())
            self.assertEqual(track.stat().st_mode & 0o777, 0o644)
            self.assertTrue(run.REVIEW_ARCHIVE.exists())
            with tarfile.open(run.REVIEW_ARCHIVE, "r:gz") as tar:
                members = tar.getnames()
                self.assertEqual(members, [
                    "Attachment.2022.en.srt",
                    "Attachment.2022.Tuned-E4B.ja.srt",
                    "review-manifest.json",
                ])
                self.assertEqual(tar.extractfile(members[0]).read(),sample())
                manifest = json.load(tar.extractfile(members[2]))
                self.assertEqual(manifest["model"],run.tuned.MODEL)
                self.assertTrue(manifest["quality_status"].startswith(
                    "machine-translated review"))
            self.assertEqual(st.jobs()[0]["status"], "published")
            # Archive bytes are stable; repeated read-only/idempotent
            # export does not overwrite the already-created review track.
            archived = run.REVIEW_ARCHIVE.read_bytes()
            run.export_review(st, info)
            self.assertEqual(run.REVIEW_ARCHIVE.read_bytes(), archived)
            self.assertEqual(self.original_ja.read_bytes(), self.original_bytes)
        finally:
            st.cn.close()

    def test_conflicting_review_sidecar_is_never_overwritten(self):
        info = self.prepare()
        st = self.fill(info)
        target = self.video.with_name(
            self.video.stem + run.REVIEW_TRACK_SUFFIX)
        target.write_bytes(b"human correction, must stay")
        try:
            with self.assertRaisesRegex(RuntimeError, "different contents"):
                run.export_review(st, info)
            self.assertEqual(target.read_bytes(),b"human correction, must stay")
            self.assertEqual(self.original_ja.read_bytes(),self.original_bytes)
        finally:
            st.cn.close()

    def test_does_not_copy_legacy_model_japanese_into_new_job(self):
        info = self.prepare()
        with sqlite3.connect(self.new/"jobs.sqlite3") as cn:
            existing = cn.execute(
                "SELECT count(*) FROM cues WHERE japanese IS NOT NULL").fetchone()[0]
        self.assertEqual(existing,0)
        self.assertNotEqual(self.new,self.old)

    def test_no_actual_generic_model_or_hy_call(self):
        with patch.object(run.tuned, "model_preflight",return_value={
            "model":run.tuned.MODEL}), patch.object(run.main, "run") as main_run:
            info = self.prepare()
            def fake_run(st, base, root, args, translator):
                self.assertIsNot(translator,service.translation_call)
                self.assertEqual(root,self.new)
                self.assertFalse(args.publish)
                self.assertEqual(args.mode,"translate")
                st.record_japanese(info["job_id"],
                                   {str(i):f"訳文{i}。" for i in range(1,4)})
                st.state(info["job_id"],"translated")
            main_run.side_effect = fake_run
            run.run_worker(info["job_id"])
            self.assertEqual(main_run.call_count,1)
            self.assertTrue(run.REVIEW_ARCHIVE.is_file())
            self.assertEqual(self.original_ja.read_bytes(),self.original_bytes)


if __name__ == "__main__":
    unittest.main()
