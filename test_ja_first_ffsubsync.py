"""Offline checks for ffsubsync source preservation and correction gates."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import hashlib

# The whole repo's test suite shares one process. Restore import search order
# immediately so this test does not alter unrelated legacy test imports.
TOOLS = str(Path(__file__).resolve().parent / "tools")
sys.path.insert(0, TOOLS)
try:
    import ja_first_ffsubsync as sync
finally:
    sys.path.remove(TOOLS)


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

    def overlap_case(self, total, overlap_indices, overlap_ms=700):
        # Roughly 25-minute episode, Japanese dialogue and realistic 3.4s
        # cue spacing. Only selected cue ends are extended past the next start.
        duration = 1520.
        cues = []
        for i in range(total):
            start = 21000 + i*3400
            end = start + 1950
            if i in overlap_indices:
                end = 21000 + (i+1)*3400 + overlap_ms
            cues.append(f"{i+1}\n{clock(start)} --> {clock(end)}\n日本語の字幕です{i}")
        return ("\n\n".join(cues)+"\n").encode(), duration

    def test_iasip_s12e05_overlap_profile_can_be_healed(self):
        source,runtime = self.overlap_case(410,set(range(0,105,7)))
        from bruiser_ja_movie_rescue import health
        self.assertEqual(health(sync.parse_cues(source),runtime)["overlap_events"],15)
        corrected,summary=sync.repair_minor_overlaps(source,runtime)
        self.assertEqual(summary["overlap_repaired_cues"],15)
        self.assertTrue(health(sync.parse_cues(corrected),runtime)["ok"])
        self.assertEqual(sync.check_alignment(source,corrected,runtime)["mode"],"corrected")
        self.assertEqual([x["text"] for x in sync.parse_cues(source)],
                         [x["text"] for x in sync.parse_cues(corrected)])
        self.assertEqual([x["start"] for x in sync.parse_cues(source)],
                         [x["start"] for x in sync.parse_cues(corrected)])

    def test_iasip_s12e04_overlap_profile_can_be_healed(self):
        source,runtime=self.overlap_case(422,set(range(0,322,7)))
        from bruiser_ja_movie_rescue import health
        self.assertEqual(health(sync.parse_cues(source),runtime)["overlap_events"],46)
        corrected,summary=sync.repair_minor_overlaps(source,runtime)
        self.assertEqual(summary["overlap_repaired_cues"],46)
        self.assertTrue(health(sync.parse_cues(corrected),runtime)["ok"])
        self.assertEqual(sync.check_alignment(source,corrected,runtime)["mode"],"corrected")

    def test_overlaps_too_severe_to_clip_are_held(self):
        source,runtime=self.overlap_case(410,set(range(0,105,7)),overlap_ms=2400)
        with self.assertRaisesRegex(RuntimeError,"unsafe_trim"):
            sync.repair_minor_overlaps(source,runtime)

    def test_zero_length_simultaneous_cue_cannot_be_repaired(self):
        source,runtime=self.overlap_case(410,set(range(0,105,7)))
        cues=sync.parse_cues(source)
        cues[1]["start"]=cues[0]["start"]
        cues[1]["end"]=cues[0]["end"]
        # Rendering exactly overlapping cues with equal starts must hold.
        rendered="\n\n".join(
            f'{i+1}\n{clock(c["start"])} --> {clock(c["end"])}\n{c["text"]}'
            for i,c in enumerate(cues)
        ).encode()
        with self.assertRaisesRegex(RuntimeError,"unsafe_trim"):
            sync.repair_minor_overlaps(rendered,runtime)

    def test_healthy_source_is_unchanged(self):
        original,_=case()
        repaired,details=sync.repair_minor_overlaps(original,5368.5)
        self.assertEqual(repaired,original)
        self.assertEqual(details["overlap_repaired_cues"],0)

    def test_prepare_rechecks_repaired_candidate_and_keeps_source_bytes(self):
        from unittest.mock import Mock
        jid="f"*32
        original,runtime=self.overlap_case(410,set(range(0,105,7)))
        qa=sync.gate.validate_srt(original,runtime)
        with patch.object(sync.gate,"read_inventory",
                          return_value={"host_path":"/mock/video.mkv"}) as inv, \
             patch.object(sync.gate,"verify_search_identity"), \
             patch.object(sync.gate,"read_staging",
                          return_value=(Path("/private/staged.srt"),original,
                                        {"video_seconds":runtime,
                                         "cues":qa["cues"]})), \
             patch.object(sync.gate,"safe_media_path",
                          return_value=Path("/mock/video.mkv")), \
             patch.object(sync.gate,"ffprobe_streams",
                          return_value=([{"codec_type":"audio"}],None)), \
             patch.object(sync.gate,"check_no_existing_ja"), \
             patch.object(sync.gate,"subprocess_duration",return_value=runtime), \
             patch.object(sync.gate,"video_target",
                          return_value=Path("/mock/video.ja.srt")), \
             patch.object(sync.source_quality,"require_not_garbage",
                          return_value={"ok":True}):
            result=sync.prepare(jid,"12345",aligner=lambda video,raw: raw)
        self.assertEqual(result["original"],original)
        self.assertNotEqual(result["chosen"],original)
        self.assertEqual(result["assessment"]["mode"],"corrected")
        self.assertEqual(result["assessment"]["overlap_repaired_cues"],15)

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
