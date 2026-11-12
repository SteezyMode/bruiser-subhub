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

    def test_missing_metadata_cue_is_identified_without_approving_sync(self):
        def varied(times,labels):
            def stamp(x):
                h,rem=divmod(x,3600)
                m,sec=divmod(rem,60)
                return f"{h:02d}:{m:02d}:{sec:02d},000"
            parts=[f"{i}\n{stamp(t)} --> {stamp(t+1)}\n{label}"
                   for i,(t,label) in enumerate(zip(times,labels),1)]
            return ("\n\n".join(parts)+"\n").encode("utf-8")
        names=["字幕版の注意書き"]+[f"台詞の番号{i}" for i in range(1,11)]
        source=varied(list(range(10,120,10)),names)
        output=varied(list(range(22,122,10)),names[1:])
        result=trial._evaluate(source,output,145)
        self.assertFalse(result["safe_dialogue"])
        self.assertEqual(result["failure"],"cue_count_changed")
        self.assertEqual(result["matching_dialogue_cues"],10)
        self.assertEqual(result["cue_edits"][0]["source_cues"][0]["number"],1)
        self.assertIn("注意書き",result["cue_edits"][0]["source_cues"][0]["text"])
        self.assertTrue(result["diagnostic_only"])
        self.assertNotIn("validated_independently",result)

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
