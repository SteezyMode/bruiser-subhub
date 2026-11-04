"""Offline regression tests for the production subtitle-tuned E4B contract.

No Ollama server, model download, media access or database mutation outside
Python temporary directories.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import subtitle_tuned_production as tuned


class SubtitleTunedProductionTests(unittest.TestCase):
    def test_selected_identity_and_exact_card_runtime(self):
        self.assertEqual(service.GEMMA, tuned.MODEL)
        self.assertEqual(tuned.MODEL_ID_PREFIX, "9ccfc3b07081")
        self.assertEqual(tuned.NUM_CTX, 1344)
        self.assertEqual(tuned.NUM_PREDICT, 256)
        self.assertEqual(tuned.TEMPERATURE, 0)
        system = tuned.messages("Hello.")[0]["content"]
        self.assertIn("Translate English subtitles into Japanese", system)
        self.assertIn("STYLE: neutral.", system)
        self.assertIn("Translate only CURRENT_SOURCE", system)
        self.assertNotIn("RULES: Speakers name:", system)
        self.assertNotIn("adult horror", system)
        self.assertNotIn("natural_8", system)

    def test_native_previous_context_is_context_only(self):
        req = tuned.messages("No.", ("Why?", "なぜ？"))
        user = req[1]["content"]
        self.assertEqual(user.count("[CURRENT_SOURCE]"), 1)
        self.assertEqual(user.count("[PREVIOUS_SOURCE]"), 1)
        self.assertEqual(user.count("[PREVIOUS_TRANSLATION]"), 1)
        self.assertTrue(user.endswith("[CURRENT_SOURCE]\nNo."))

    def test_every_call_uses_one_current_source_and_card_limits(self):
        requests = []
        def post(endpoint, body, timeout=0):
            requests.append(body)
            return {"model": tuned.MODEL,
                    "message": {"content": "いいえ。"},
                    "done_reason": "stop"}
        self.assertEqual(tuned.translation("No.", post=post), "いいえ。")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["options"], {
            "temperature": 0, "num_ctx": 1344, "num_predict": 256,
        })
        self.assertEqual(requests[0]["messages"][1]["content"],
                         "[CURRENT_SOURCE]\nNo.")

    def test_full_source_context_crosses_batch_boundary(self):
        original = [
            {"cue_id": 11, "english": "Why?", "japanese": "なぜ？"},
            {"cue_id": 12, "english": "No.", "japanese": None},
            {"cue_id": 13, "english": "Stop!", "japanese": None},
        ]
        requests = []
        def post(path, body, timeout=0):
            self.assertEqual(path, "/api/chat")
            requests.append(body["messages"][1]["content"])
            return {"model": tuned.MODEL,
                    "message": {"content": "いいえ。" if len(requests) == 1
                                else "やめて！"},
                    "done_reason": "stop"}
        result = tuned.translate_selected(original[1:], original, post=post)
        self.assertEqual(result, {"12": "いいえ。", "13": "やめて！"})
        self.assertIn("[PREVIOUS_SOURCE]\nWhy?", requests[0])
        self.assertIn("[PREVIOUS_TRANSLATION]\nなぜ？", requests[0])
        self.assertIn("[PREVIOUS_SOURCE]\nNo.", requests[1])
        self.assertIn("[PREVIOUS_TRANSLATION]\nいいえ。", requests[1])

    def test_no_wrong_model_or_old_json_style(self):
        with self.assertRaisesRegex(RuntimeError, "model override refused"):
            service.translation_call(None, [], "", model="gemma4:e4b-it-qat")
        with self.assertRaisesRegex(RuntimeError, "style prompt"):
            service.translation_call(None, [], "", style="natural_8")

    def test_existing_non_tuned_partial_cues_are_not_reused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job = {"id": "daily-test", "source_sha": "a"*64}
            with self.assertRaisesRegex(RuntimeError, "prior model"):
                tuned.assert_job_profile(root, job, 2)
            self.assertFalse((root/"model-profiles").exists())
            profile = tuned.assert_job_profile(root, job, 0)
            self.assertEqual(json.loads(profile.read_text())["model"], tuned.MODEL)
            self.assertEqual(tuned.assert_job_profile(root, job, 2), profile)
            with self.assertRaisesRegex(RuntimeError, "Mixed-model"):
                tuned.assert_job_profile(
                    root, dict(job, source_sha="b"*64), 2)

    def test_model_preflight_fails_on_wrong_digest_before_warmup(self):
        actions = []
        def post(endpoint, body=None, timeout=15):
            actions.append(endpoint)
            if endpoint == "/api/tags":
                return {"models": [{"name": tuned.MODEL, "digest": "wrong"}]}
            raise AssertionError("Unexpected network action")
        with self.assertRaisesRegex(RuntimeError, "Wrong subtitle model digest"):
            tuned.model_preflight(post)
        self.assertEqual(actions, ["/api/tags"])

    def test_model_preflight_requires_full_gpu_residency(self):
        def post(endpoint, body=None, timeout=15):
            if endpoint == "/api/tags":
                return {"models": [{"name": tuned.MODEL,
                                    "digest": tuned.MODEL_ID_PREFIX + "a"*52}]}
            if endpoint == "/api/show":
                return {"details": {"family": "gemma4"},
                        "template": "{{ .Prompt }}"}
            if endpoint == "/api/ps":
                return {"models": [{"name": tuned.MODEL,
                                    "size": 5_000_000_000,
                                    "size_vram": 4_000_000_000}]}
            raise AssertionError("Unexpected model generation")
        with self.assertRaisesRegex(RuntimeError, "not fully GPU-resident"):
            tuned.model_preflight(post)

    def test_model_preflight_reports_known_quantization_discrepancy(self):
        def post(endpoint, body=None, timeout=15):
            if endpoint == "/api/tags":
                return {"models": [{"name": tuned.MODEL,
                                    "digest": tuned.MODEL_ID_PREFIX + "a"*52}]}
            if endpoint == "/api/show":
                return {"details": {"family": "gemma4",
                                    "quantization_level": "Q4_K_M"},
                        "template": "{{ .Prompt }}"}
            if endpoint == "/api/ps":
                return {"models": [{"name": tuned.MODEL,
                                    "size": 5_000_000_000,
                                    "size_vram": 5_000_000_000}]}
            raise AssertionError("Unexpected model generation")
        result = tuned.model_preflight(post)
        self.assertEqual(result["gpu_resident_pct"], 100.0)
        self.assertEqual(result["reported_quantization"], "Q4_K_M")


if __name__ == "__main__":
    unittest.main()
