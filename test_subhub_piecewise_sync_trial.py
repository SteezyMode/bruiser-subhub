"""Unit coverage for dry-run global vs piecewise timing diagnostics."""
import unittest

from tools import subhub_piecewise_sync_trial as trial


def srt(shifts,replace_text=False):
    blocks=[]
    for i,sec in enumerate(shifts,1):
        start=sec*1000
        end=start+1000
        def clk(n):
            seconds,msec=divmod(n,1000)
            h,seconds=divmod(seconds,3600)
            m,sec=divmod(seconds,60)
            return f"{h:02}:{m:02}:{sec:02},{msec:03}"
        line="そのまま" if not (replace_text and i==2) else "別の内容"
        blocks.append(f"{i}\n{clk(start)} --> {clk(end)}\n{line}")
    return ("\n\n".join(blocks)+"\n").encode("utf-8")


class DryRunComparisonTests(unittest.TestCase):
    def test_piecewise_reports_three_timeline_regions_and_never_approves(self):
        original=srt([10,20,30,40,50,60,70,80,90])
        changed=srt([12,22,32,44,54,64,75,85,95])
        result=trial._evaluate(original,changed,110)
        self.assertTrue(result["safe_dialogue"])
        self.assertEqual(result["shift_median_by_third"],[2,4,5])
        self.assertFalse(result["validated_independently"])
        self.assertFalse(result["reordered"])

    def test_changed_japanese_or_missing_cue_never_passes(self):
        original=srt([10,20,30,40,50,60,70,80,90])
        self.assertEqual(
            trial._evaluate(original,srt([10,20,30,40,50,60,70,80,90],
                                         replace_text=True),110)["failure"],
            "dialogue_text_changed")
        self.assertEqual(
            trial._evaluate(original,srt([10,20,30,40,50,60,70,80]),110)["failure"],
            "cue_count_changed")


if __name__=="__main__":
    unittest.main()
