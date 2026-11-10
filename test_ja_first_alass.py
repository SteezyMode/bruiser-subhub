"""Offline unit tests: standalone alass split/framerate correction safety."""
from pathlib import Path
import sys
import unittest

TOOLS=str(Path(__file__).resolve().parent/"tools")
sys.path.insert(0,TOOLS)
try:
    import ja_first_alass as alass
finally:
    sys.path.pop(0)

def clock(ms):
    h, rem=divmod(ms,3600000)
    m, rem=divmod(rem,60000)
    s,ms=divmod(rem,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def fixture(shift):
    source=[]
    corrected=[]
    for i in range(180):
        start=30_000+5_000*i
        end=start+2_000
        ja=f"これは元の日本語字幕 {i} です"
        delta=int(shift(i)*1000)
        source.append(f"{i+1}\n{clock(start)} --> {clock(end)}\n{ja}")
        corrected.append(f"{i+1}\n{clock(start+delta)} --> {clock(end+delta)}\n{ja}")
    return ("\n\n".join(source)+"\n").encode(),("\n\n".join(corrected)+"\n").encode()

class AlassTests(unittest.TestCase):
    def test_three_section_correction_preserved(self):
        raw,aligned=fixture(lambda i: -1.91 if i<40 else .25 if i<150 else 2.3)
        summary=alass.assess(raw,aligned,1500)
        self.assertEqual(summary["mode"],"aligned")
        self.assertTrue(summary["nonuniform_correction"])
        self.assertLess(summary["shift_min_s"],-1.8)
        self.assertGreater(summary["shift_max_s"],2.2)
        self.assertEqual(summary["cues"],180)
        self.assertNotEqual(summary["source_sha256"],summary["aligned_sha256"])

    def test_unchanged_dialogue(self):
        raw,_=fixture(lambda i:0)
        summary=alass.assess(raw,raw,1500)
        self.assertEqual(summary["mode"],"original")

    def test_dialogue_must_remain_byte_equivalent_after_parse(self):
        raw,aligned=fixture(lambda i:-1)
        modified=aligned.replace("これは元の日本語字幕 20".encode(),
                                 "これは別の字幕 20".encode())
        with self.assertRaisesRegex(RuntimeError,"dialogue_changed"):
            alass.assess(raw,modified,1500)

    def test_extreme_misalignment_held(self):
        raw,aligned=fixture(lambda i:130)
        with self.assertRaisesRegex(RuntimeError,"extreme_shift"):
            alass.assess(raw,aligned,1800)

if __name__=="__main__":
    unittest.main()
