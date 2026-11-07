"""Offline regression tests for the live American Dad batch safety gates.

Loads only selected pure functions from the worker's AST so no movie library,
CUDA, llama.cpp, user services or private model is needed to test behavior.
"""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

PATH = Path(__file__).resolve().parent / "tools/plamo8b_american_dad_existing_en_batch.py"
SOURCE = PATH.read_text("utf-8")
TREE = ast.parse(SOURCE)
NAMES = {"thermal_gate", "translate_with_one_retry", "episode_only_cue_failure"}
NODES = [node for node in TREE.body
         if isinstance(node, ast.FunctionDef) and node.name in NAMES]
RETRY_ERRORS = {"missing_model_completion", "model_output_truncated",
                "empty_or_malformed_model_output"}


def functions(extra=None):
    scope = {
        "re": re,
        "CUE_MODEL_RETRY_ERRORS": frozenset(RETRY_ERRORS),
        "engine": SimpleNamespace(SPOKEN="translated"),
    }
    if extra:
        scope.update(extra)
    exec(compile(ast.Module(body=NODES, type_ignores=[]), str(PATH), "exec"),
         scope)
    return scope


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def run_cooling(readings):
    clock = Clock()
    samples = iter(readings)
    outputs = []
    scope = functions({
        "time": clock,
        "temperatures": lambda: next(samples),
        "CPU_PAUSE": 79.0, "CPU_RESUME": 73.0, "CPU_ABORT": 90.0,
        "GPU_PAUSE": 73.0, "GPU_RESUME": 67.0, "GPU_ABORT": 83.0,
        "COOL_TIMEOUT": 1200,
        "print": lambda *args, **kwargs: outputs.append(" ".join(map(str,args))),
    })
    scope["thermal_gate"]()
    return clock.sleeps, outputs


class ThermalTests(unittest.TestCase):
    def test_below_limits_never_sleeps(self):
        sleeps, outputs = run_cooling([(72, 70)])
        self.assertEqual(sleeps, [])
        self.assertEqual(outputs, [])

    def test_cpu_only_does_not_wait_for_never_overheated_gpu(self):
        sleeps, outputs = run_cooling([(80, 70), (73, 70)])
        self.assertEqual(sleeps, [5])
        self.assertTrue(any("THERMAL_RESUME" in x for x in outputs))

    def test_gpu_only_does_not_wait_for_never_overheated_cpu(self):
        sleeps, outputs = run_cooling([(77, 74), (76, 67)])
        self.assertEqual(sleeps, [5])
        self.assertTrue(any("THERMAL_RESUME" in x for x in outputs))

    def test_both_overheated_must_cool(self):
        sleeps, _ = run_cooling([(80, 74), (73, 70), (72, 67)])
        self.assertEqual(sleeps, [5, 5])

    def test_second_sensor_crossing_pause_is_also_honored(self):
        sleeps, _ = run_cooling([(80, 70), (75, 74), (73, 70), (72, 67)])
        self.assertEqual(sleeps, [5, 5, 5])

    def test_hardware_abort_remains_fatal(self):
        with self.assertRaisesRegex(RuntimeError, "THERMAL_ABORT"):
            run_cooling([(90, 55)])


class UntranslatedCueTests(unittest.TestCase):
    def test_once_held_then_japanese_accepted(self):
        attempts = []
        def caller(*args):
            attempts.append(args)
            return ("OK", {}, "held_non_japanese") if len(attempts) == 1 else ("はい", {}, "translated")
        got = functions()["translate_with_one_retry"](caller, 1, "OK", [("Previous","前の文")])
        self.assertEqual(got[0], "はい")
        self.assertEqual(len(attempts), 2)

    def test_two_bad_outputs_hold_episode(self):
        attempts = []
        def caller(*args):
            attempts.append(1)
            return ("Roger", {}, "held_non_japanese")
        got = functions()["translate_with_one_retry"](caller, 1, "Roger", [("Previous","前の文")])
        self.assertEqual(got[2], "held_non_japanese")
        self.assertEqual(len(attempts), 2)
        self.assertTrue(functions()["episode_only_cue_failure"](
            RuntimeError("model_did_not_translate_spoken_cue_117")))

    def test_malformed_response_can_retry_once(self):
        attempts = []
        def caller(*args):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("empty_or_malformed_model_output")
            return "はい", {}, "translated"
        got = functions()["translate_with_one_retry"](caller, 1, "yes", [("Previous","前の文")])
        self.assertEqual(got[0], "はい")
        self.assertEqual(len(attempts), 2)

    def test_repeated_bad_model_output_marks_episode_only(self):
        def caller(*args):
            raise RuntimeError("model_output_truncated")
        got=functions()["translate_with_one_retry"](
            caller, 1, "yes", [("Previous","前の文")])
        self.assertEqual(got[0],"yes")
        self.assertEqual(got[2],"held_non_japanese")

    def test_real_infrastructure_errors_are_fatal(self):
        def caller(*args):
            raise RuntimeError("batch_llama_server_exited__check_private_log")
        with self.assertRaisesRegex(RuntimeError, "batch_llama_server_exited"):
            functions()["translate_with_one_retry"](caller, 1, "yes", [])
        for message in ("THERMAL_ABORT", "checkpoint_source_mismatch",
                        "GPU_IN_USE", "batch_llama_server_exited__check_private_log"):
            self.assertFalse(functions()["episode_only_cue_failure"](
                RuntimeError(message)))

    def test_batch_handles_only_cue_held_and_does_not_hide_fatal_failures(self):
        self.assertIn("if episode_only_cue_failure(exc):", SOURCE)
        self.assertIn('append_result("episode_held",tag,str(exc))', SOURCE)
        self.assertIn('append_result("paused",tag,str(exc))', SOURCE)
        self.assertIn("with_batch_inference(tag,video,cues,origin,raw_sha,timing)", SOURCE)


if __name__ == "__main__":
    unittest.main()
