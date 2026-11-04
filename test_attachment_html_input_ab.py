"""Offline test for the one-variable Attachment E4B HTML input A/B.

No Ollama, media, or non-temporary SQLite access.
"""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import attachment_html_input_ab as lab


class AttachmentHTMLInputABTests(unittest.TestCase):
    def test_removes_only_known_presentation_tags(self):
        s='<font face="Tahoma" color="#eeeeee">It <i>sounds</i> good.</font>'
        self.assertEqual(lab.clean_presentation(s), "It sounds good.")
        self.assertEqual(lab.clean_presentation("A < B"),"A < B")
        self.assertEqual(lab.clean_presentation("She said: 'No'."),"She said: 'No'.")
        self.assertEqual(lab.clean_presentation("A\nB"),"A\nB")
        with self.assertRaises(ValueError):
            lab.clean_presentation("<script>alert(1)</script>")

    def test_keep_same_previous_japanese_in_both_arms(self):
        source='<font face="Tahoma">No.</font>'
        prev=('<font face="Tahoma">Why?</font>',"なぜ？")
        raw,rawprev=lab.input_pair(source,prev,clean=False)
        clean,cleanprev=lab.input_pair(source,prev,clean=True)
        self.assertEqual(raw,source)
        self.assertEqual(clean,"No.")
        self.assertEqual(rawprev,prev)
        self.assertEqual(cleanprev,("Why?","なぜ？"))
        self.assertEqual(rawprev[1],cleanprev[1])

    def test_trial_keeps_model_params_identical_and_reuses_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            out=root/"markup-ab"
            cues={}
            for cue_id in lab.CUES:
                for i in (cue_id-1,cue_id):
                    if i not in cues:
                        cues[i]={"cue_id":i,"timing":"00:00:01,000 --> 00:00:02,000",
                                 "english":f'<font face="Tahoma">Line {i}.</font>',
                                 "japanese":f"行{i}"}
            job={"id":lab.JOB,"source_sha":"a"*64}
            calls=[]
            def translate(current,previous=None):
                calls.append((current,previous))
                return "マークアップなし" if "<font" not in current else "マークアップあり"
            with patch.object(lab,"original_cues",return_value=(job,cues)), \
                 patch.object(lab.main,"lockfiles",side_effect=lambda root:nullcontext()), \
                 patch.object(lab.main,"thermal_guard"), \
                 patch.object(lab.tuned,"model_preflight",return_value={}), \
                 patch.object(lab.tuned,"translation",side_effect=translate):
                result=lab.trial(root,out)
                self.assertEqual(len(calls),48)
                self.assertEqual(len(result["results"]),24)
                self.assertTrue(all("<font" in calls[i][0] for i in range(0,48,2)))
                self.assertTrue(all("<font" not in calls[i][0] for i in range(1,48,2)))
                self.assertTrue(all(calls[i][1][1] == calls[i+1][1][1]
                                    for i in range(0,48,2)))
                self.assertTrue((out/"report.json").is_file())
                self.assertEqual(json.loads((out/"manifest.json").read_text())["options"],
                                 {"temperature":0,"num_ctx":1344,"num_predict":256})
                # No redundant GPU calls on restart; create-only report stable.
                another=lab.trial(root,out)
                self.assertEqual(len(calls),48)
                self.assertEqual(result,another)

    def test_refuse_changed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"test.json"
            lab.create_record(p,{"x":1})
            lab.create_record(p,{"x":1})
            with self.assertRaisesRegex(RuntimeError,"Conflicting"):
                lab.create_record(p,{"x":2})


if __name__=="__main__":
    unittest.main()
