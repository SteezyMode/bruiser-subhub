"""Offline checks for lossless handling of wrong-duration Japanese subtitle downloads."""
import ast
import re
import unittest

from tools import ja_first_stage_saved_batch as stage


def worker_analyzer():
    """Execute only the pure subtitle analyzer, never provider/container code."""
    parsed = ast.parse(stage.WORKER)
    keep = []
    names = {"MAX_BYTES", "SRT_TIMING", "ASS_TIMING", "JAPANESE", "TAGS"}
    for node in parsed.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names
            for target in node.targets
        ):
            keep.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "analyze":
            keep.append(node)
    namespace = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]),
                 "<stage-worker-analyzer>", "exec"), namespace)
    return namespace["analyze"]


def subtitle_ending(seconds):
    lines = []
    for index in range(100):
        end = int((index+1)/100*seconds)
        start = max(0, end-2)
        def stamp(t):
            h,rest = divmod(t,3600)
            m,s = divmod(rest,60)
            return f"{h:02}:{m:02}:{s:02},000"
        lines.append(f"{index+1}\n{stamp(start)} --> {stamp(end)}\n日本語の字幕")
    return ("\n\n".join(lines)+"\n").encode("utf-8")


class WrongDurationTests(unittest.TestCase):
    def test_wrong_cut_held_with_metadata_and_original_bytes_retained_by_worker(self):
        fn = worker_analyzer()
        raw = subtitle_ending(8640)  # approximately US-cut 144-minute runtime
        with self.assertRaisesRegex(RuntimeError, "subtitle_duration_inconsistent"):
            fn(raw, 7176)  # 119.6 minute European cut
        record = fn(raw, 7176, allow_duration_mismatch=True)
        self.assertTrue(record["duration_mismatch"])
        self.assertEqual(record["cues"],100)
        self.assertAlmostEqual(record["last_end_video_ratio"],8640/7176,places=3)

    def test_matching_cut_stays_publish_eligible_subject_to_later_sync(self):
        record=worker_analyzer()(subtitle_ending(7000),7176,
                                  allow_duration_mismatch=True)
        self.assertFalse(record["duration_mismatch"])

    def test_host_retains_wrong_duration_in_isolated_private_status(self):
        source=stage.run_one.__code__.co_consts
        self.assertIn("held_duration_mismatch",str(source))
        self.assertIn("held_duration_mismatch",stage.rejected_duration_candidates.__code__.co_consts.__str__())


if __name__=="__main__":
    unittest.main()
