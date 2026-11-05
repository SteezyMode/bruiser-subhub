"""Offline tests for PLaMo 8B trial. Never download weights or run a model."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import plamo3_8b_challenger as trial
from tools import plamo3_real_film_ab as real
from tools import plamo3_small_ab as small


class Plamo8BTests(unittest.TestCase):
    def test_creator_native_prompt_and_frozen_identity(self):
        trial.self_test()
        trial.check_native_contract()
        self.assertEqual(
            trial.EXPECTED_SOURCE_SHA256,
            "d4394793c9608ab8935cdba89a6bfb9be41d0e51e1274123966b78939fe1174a",
        )
        self.assertEqual(real.HISTORY, 2)
        self.assertEqual(real.STOP, ["<|plamo:tag|>", "<|plamo:bos|>"])

    def test_model_8b_file_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "8b.gguf"
            path.write_bytes(b"GGUF" + b"X" * 20)
            with self.assertRaisesRegex(RuntimeError, "missing_or_incomplete"):
                trial.validate_weight(path)
            with mock.patch.object(
                Path, "stat",
                autospec=True,
                side_effect=lambda p: mock.Mock(st_size=5_280_000_000),
            ):
                with path.open("rb") as fh:
                    self.assertEqual(fh.read(4), b"GGUF")
                trial.validate_weight(path)

    def test_gpu_layer_offload_is_only_runtime_variation(self):
        attempts = []
        def fake_start(binary, model, port, ngl, logfile):
            attempts.append(ngl)
            if ngl == 28:
                raise RuntimeError("llama_server_exited_early_check_private_log")
            return object()
        with mock.patch.object(trial.small, "start_server", side_effect=fake_start):
            process, selected = trial.start_offloaded_server(
                "binary", "model", Path("/tmp"), 18882)
        self.assertIsNotNone(process)
        self.assertEqual(selected, 20)
        self.assertEqual(attempts, [28, 20])

    def test_native_model_request_not_reinvented(self):
        with mock.patch.object(
            trial.real, "request", return_value=("はっきり言え。", {}, "translated")
        ) as called:
            with tempfile.TemporaryDirectory() as d:
                cue = small.samples()[0]
                record = {"entries": [], "status": "started"}
                trial.evaluate(18882, [cue], record, Path(d))
            called.assert_called_once_with(18882, cue["english"], [])
            self.assertEqual(record["entries"][0]["status"], "translated")
            self.assertEqual(record["entries"][0]["start"], cue["start"])
            self.assertEqual(record["entries"][0]["end"], cue["end"])

    def test_non_dialogue_caption_does_not_call_model(self):
        with mock.patch.object(trial.real, "request") as request:
            with tempfile.TemporaryDirectory() as d:
                cue = dict(small.samples()[0])
                cue["english"] = '<font size="36">[SIGHS]</font>'
                record = {"entries": [], "status": "started"}
                trial.evaluate(18882, [cue], record, Path(d))
            request.assert_not_called()
            self.assertEqual(record["entries"][0]["japanese"], cue["english"])
            self.assertEqual(record["entries"][0]["status"], "non_dialogue_passthrough")

    def test_reference_only_accepts_completely_identical_en(self):
        rows = [
            {"number": i+153, "start": small.timestamp(i*5),
             "end": small.timestamp(i*5+4), "english": "Test."}
            for i in range(100)
        ]
        payload = {
            "status": "complete",
            "entries": [dict(row, status="translated", japanese="テスト")
                        for row in rows],
        }
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            refdir = base / trial.ORIGINAL_08
            refdir.mkdir(mode=0o700)
            p = refdir / "0.8b.json"
            p.write_text(json.dumps(payload))
            p.chmod(0o600)
            with mock.patch.object(trial.real, "load_frozen_run") as loader:
                loader.return_value = (None, None, rows, 0, None, None, None,
                                       trial.EXPECTED_SOURCE_SHA256)
                got = trial.read_proven_reference(
                    base, trial.ORIGINAL_08, "0.8b", rows)
                self.assertEqual(got, hashlib.sha256(p.read_bytes()).hexdigest())
                loader.return_value = (None, None, rows, 0, None, None, None,
                                       "0" * 64)
                with self.assertRaisesRegex(RuntimeError, "not_identical"):
                    trial.read_proven_reference(base, trial.ORIGINAL_08, "0.8b", rows)


if __name__ == "__main__":
    unittest.main()
