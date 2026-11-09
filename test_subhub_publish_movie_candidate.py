"""Offline checks for host publication of approved Japanese movie subtitles."""
import hashlib
import unittest
from tools import subhub_publish_movie_candidate as movie

def clock(t):
    return f"{t//3600:02}:{t//60%60:02}:{t%60:02},000"

def sample(shift=0,text="日本語で話します"):
    return ("\n\n".join(
        f"{i+1}\n{clock(i*40+shift)} --> {clock(i*40+shift+3)}\n{text}"
        for i in range(200))+"\n").encode()

class HostPublisherTests(unittest.TestCase):
    def setUp(self):
        self.original=sample()
        self.aligned=sample(2)
        self.report={
            "sha256":hashlib.sha256(self.original).hexdigest(),
            "quality_gate":{"ok":True,"video_seconds":8627},
            "sync_preview":{"ok":True},
        }

    def test_verified_japanese_alignment(self):
        self.assertEqual(movie.verify_candidate(
            self.original,self.aligned,8627,self.report),200)

    def test_no_retranslated_or_changed_dialogue(self):
        with self.assertRaisesRegex(RuntimeError,"alignment_changed_dialogue"):
            movie.verify_candidate(
                self.original,sample(2,"違うセリフ"),8627,self.report)

    def test_original_checksum_mismatch(self):
        with self.assertRaisesRegex(RuntimeError,"source_checksum_mismatch"):
            movie.verify_candidate(sample(4),self.aligned,8627,self.report)

    def test_unapproved_sync_rejected(self):
        self.report["sync_preview"]["ok"]=False
        with self.assertRaisesRegex(RuntimeError,"not_previously_approved"):
            movie.verify_candidate(self.original,self.aligned,8627,self.report)

    def test_other_movie_cut_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"subtitle_duration_inconsistent"):
            movie.verify_candidate(self.original,self.aligned,7176,self.report)

    def test_only_private_report_locations(self):
        self.assertIsNone(movie.REPORT.fullmatch("/tmp/fake.json"))
        self.assertIsNotNone(movie.REPORT.fullmatch(
            "/config/bruiser-ja-screened/"+"a"*20+"/report-"+"b"*20+".json"))

if __name__=="__main__":
    unittest.main()
