"""Offline checks for ffsubsync source preservation and correction gates."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import ja_first_ffsubsync as sync


def clock(milliseconds):
    milliseconds=int(milliseconds)
    s,ms=divmod(milliseconds,1000)
    hours,s=divmod(s,3600)
    minutes,seconds=divmod(s,60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def case(shift=lambda i: 0):
    original=[]
    aligned=[]
    for i in range(365):
        # Matches the observed 283 Japanese + 80 symbols + 2 Latin shape.
        words=(f"字幕の確認{i}" if i<283 else
               (f"♪{i}" if i<363 else f"OK{i}"))
        start=int((103.56 + i*(4814.91/364))*1000)
        end=start+1800
        delta=int(shift(i)*1000)
        original.append(f"{i+1}\n{clock(start)} --> {clock(end)}\n{words}")
        aligned.append(f"{i+1}\n{clock(start+delta)} --> {clock(end+delta)}\n{words}")
    return ("\n\n".join(original)+"\n").encode(), ("\n\n".join(aligned)+"\n").encode()


class FFSubsyncPipelineTests(unittest.TestCase):
    def test_exact_recovery_shape_corrected(self):
        original,corrected=case(lambda i: -19.43-4.82*i/364)
        result=sync.check_alignment(original,corrected,5368.5)
        self.assertEqual(result["mode"],"corrected")
        self.assertEqual(result["cues"],365)
        self.assertEqual(result["japanese_fraction"],0.993)
        self.assertGreater(result["shift_range_seconds"][1]-
                           result["shift_range_seconds"][0],4.7)

    def test_already_aligned_keeps_original(self):
        raw,synced=case(lambda i: -0.05)
        result=sync.check_alignment(raw,synced,5368.5)
        self.assertEqual(result["mode"],"original")

    def test_large_or_inconsistent_offset_held(self):
        raw,bad=case(lambda i: -31.0)
        with self.assertRaisesRegex(RuntimeError,"shift_or_variation"):
            sync.check_alignment(raw,bad,5368.5)
        raw,bad=case(lambda i: -5-12*i/364)
        with self.assertRaisesRegex(RuntimeError,"shift_or_variation"):
            sync.check_alignment(raw,bad,5368.5)

    def test_changed_dialogue_cannot_publish(self):
        raw,synced=case(lambda i: -1)
        altered=synced.replace("字幕の確認100".encode(), "別の台詞".encode())
        with self.assertRaisesRegex(RuntimeError,"changed_dialogue"):
            sync.check_alignment(raw,altered,5368.5)

    def test_bind_translation_is_ro_mount_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/"library"
            folder.mkdir()
            video=folder/"Film.mkv"
            video.write_bytes(b"original")
            mapped=sync.path_in_container(video,[{
                "Type":"bind","Source":str(folder),"Destination":"/media/movies","RW":False
            }])
            self.assertEqual(mapped,"/media/movies/Film.mkv")
            self.assertEqual(video.read_bytes(),b"original")
            with self.assertRaises(RuntimeError):
                sync.path_in_container(video,[])

    def test_derived_provenance_is_private_and_idempotent(self):
        raw,aligned=case(lambda i: -19.43)
        jid="a"*32
        sid="12345"
        prepared={"jid":jid,"sid":sid,"original":raw,"chosen":aligned,
                  "assessment":sync.check_alignment(raw,aligned,5368.5)}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sync.gate,"STAGED",Path(tmp)):
                sync.preserve(prepared)
                sync.preserve(prepared)
                path=sync.record_path(jid,sid)
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_bytes(),aligned)
                self.assertTrue(sync.provenance_matches(
                    jid,sid,hashlib.sha256(raw).hexdigest(),
                    hashlib.sha256(aligned).hexdigest()))
                with self.assertRaises(RuntimeError):
                    sync.provenance_matches(jid,sid,"0"*64,
                                            hashlib.sha256(aligned).hexdigest())


if __name__=="__main__":
    unittest.main()
