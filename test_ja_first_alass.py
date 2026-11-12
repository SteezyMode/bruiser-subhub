"""Offline unit tests: standalone alass split/framerate correction safety."""
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

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

    def test_sync_keeps_original_japanese_when_engine_reflows_text(self):
        raw, aligned = fixture(lambda i: -2)
        original = "これは元の日本語字幕 20 です".encode("utf-8")
        rewrapped = "これは元の日本語\n字幕 20 です".encode("utf-8")
        self.assertIn(original, aligned)
        aligned = aligned.replace(original, rewrapped, 1)
        fixed = alass.ff.keep_source_dialogue(raw, aligned)
        src_cues = alass.ff.parse_cues(raw)
        fixed_cues = alass.ff.parse_cues(fixed)
        self.assertEqual(
            [x["text"] for x in fixed_cues],
            [x["text"] for x in src_cues])
        self.assertEqual(fixed_cues[20]["start"], src_cues[20]["start"] - 2000)
        self.assertEqual(alass.assess(raw, fixed, 1500)["mode"], "aligned")

    def test_sync_does_not_accept_changed_word_or_missing_cues(self):
        raw, aligned = fixture(lambda i: 1)
        changed = aligned.replace(
            "これは元の日本語字幕 20 です".encode("utf-8"),
            "これは別の日本語字幕 20 です".encode("utf-8"), 1)
        with self.assertRaisesRegex(RuntimeError, "sync_dialogue_changed"):
            alass.ff.keep_source_dialogue(raw, changed)
        with self.assertRaisesRegex(RuntimeError, "sync_cue_count_changed"):
            alass.ff.keep_source_dialogue(raw, aligned.rsplit(b"\n\n", 1)[0])

    def test_extreme_misalignment_held(self):
        raw,aligned=fixture(lambda i:130)
        with self.assertRaisesRegex(RuntimeError,"extreme_shift"):
            alass.assess(raw,aligned,1800)


    def test_normal_prepare_retries_audio_when_english_output_is_out_of_video(self):
        raw, good=fixture(lambda i: -2)
        _, bad=fixture(lambda i: 500)
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            video=folder/"film.mkv"
            output=folder/"film.ja.srt"
            calls=[]
            def runner(cmd,**kwargs):
                label=Path(cmd[1]).name
                calls.append(label)
                Path(cmd[3]).write_bytes(bad if label.endswith(".english.srt") else good)
                return subprocess.CompletedProcess(cmd,0,b"",b"")
            with patch.object(alass,"available",return_value=True), \
                 patch.object(alass.gate,"STAGED",folder), \
                 patch.object(alass.gate,"read_inventory",return_value={"host_path":str(video)}), \
                 patch.object(alass.gate,"verify_search_identity"), \
                 patch.object(alass.gate,"read_staging",return_value=(
                     None,raw,{"video_seconds":1100,"cues":180})), \
                 patch.object(alass.gate,"safe_media_path",return_value=video), \
                 patch.object(alass.gate,"ffprobe_streams",return_value=([],None)), \
                 patch.object(alass.gate,"check_no_existing_ja"), \
                 patch.object(alass.gate,"subprocess_duration",return_value=1100), \
                 patch.object(alass.gate,"validate_srt",return_value={"cues":180}), \
                 patch.object(alass.gate,"video_target",return_value=output), \
                 patch.object(alass.quality,"require_not_garbage",return_value={}), \
                 patch.object(alass,"_embedded_english",return_value=b"english-reference"), \
                 patch.object(alass.subprocess,"run",side_effect=runner):
                result=alass.prepare("a"*32,"123")
            self.assertEqual(result["chosen"],good)
            self.assertEqual(result["assessment"]["alignment_reference"],"video_audio")
            self.assertEqual(len(calls),2)
            self.assertFalse(output.exists())

    def test_normal_alass_prefers_valid_english_without_unnecessary_audio(self):
        raw, good=fixture(lambda i:-2)
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            calls=[]
            def runner(cmd,**kwargs):
                calls.append(Path(cmd[1]).name)
                Path(cmd[3]).write_bytes(good)
                return subprocess.CompletedProcess(cmd,0,b"",b"")
            def validator(raw_output):
                normalized=alass.ff.keep_source_dialogue(raw,raw_output)
                alass.assess(raw,normalized,1100)
                return normalized
            with patch.object(alass,"available",return_value=True), \
                 patch.object(alass.gate,"STAGED",folder), \
                 patch.object(alass,"_embedded_english",return_value=b"english-reference"):
                chosen,reference=alass.align(folder/"film.mkv",raw,
                                             validator=validator,runner=runner)
            self.assertEqual(chosen,good)
            self.assertEqual(reference,"same_video_embedded_english")
            self.assertEqual(len(calls),1)

    def test_normal_alass_holds_both_invalid_references(self):
        raw,_=fixture(lambda i:0)
        _, invalid=fixture(lambda i:500)
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            calls=[]
            def runner(cmd,**kwargs):
                calls.append(Path(cmd[1]).name)
                Path(cmd[3]).write_bytes(invalid)
                return subprocess.CompletedProcess(cmd,0,b"",b"")
            def validator(raw_output):
                alass.assess(raw,alass.ff.keep_source_dialogue(raw,raw_output),1100)
                return raw_output
            with patch.object(alass,"available",return_value=True), \
                 patch.object(alass.gate,"STAGED",folder), \
                 patch.object(alass,"_embedded_english",return_value=b"english-reference"):
                with self.assertRaisesRegex(RuntimeError,"alass_no_validated_reference"):
                    alass.align(folder/"film.mkv",raw,validator=validator,runner=runner)
            self.assertEqual(len(calls),2)

    def test_intensive_agreement_requires_every_third(self):
        raw, moved = fixture(lambda i: 0 if i<60 else 5)
        self.assertEqual(alass._intensive_agreement(raw,raw),[1.0,1.0,1.0])
        self.assertIsNone(alass._intensive_agreement(raw,moved))

    def test_intensive_never_approves_multiple_settings_of_only_audio(self):
        raw, aligned = fixture(lambda i: -2)
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d)
            def runner(cmd,**kwargs):
                Path(cmd[3]).write_bytes(aligned)
                return subprocess.CompletedProcess(cmd,0,b"",b"")
            with patch.object(alass,"available",return_value=True), \
                 patch.object(alass.gate,"STAGED",directory), \
                 patch.object(alass.gate,"subprocess_duration",return_value=1100), \
                 patch.object(alass.gate,"validate_srt",return_value={"cues":180}), \
                 patch.object(alass,"_embedded_english",return_value=None), \
                 patch.object(alass,"_intensive_external_english",return_value=None):
                with self.assertRaisesRegex(RuntimeError,"missing_english_reference"):
                    alass.intensive_align(directory/"video.mkv",raw,runner=runner)

    def test_intensive_requires_external_or_embedded_to_agree_with_audio(self):
        raw, aligned = fixture(lambda i: -2)
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d)
            def runner(cmd,**kwargs):
                Path(cmd[3]).write_bytes(aligned)
                return subprocess.CompletedProcess(cmd,0,b"",b"")
            with patch.object(alass,"available",return_value=True), \
                 patch.object(alass.gate,"STAGED",directory), \
                 patch.object(alass.gate,"subprocess_duration",return_value=1100), \
                 patch.object(alass.gate,"validate_srt",return_value={"cues":180}), \
                 patch.object(alass,"_embedded_english",return_value=None), \
                 patch.object(alass,"_intensive_external_english",return_value=b"trusted-en-reference"):
                chosen,details=alass.intensive_align(directory/"video.mkv",raw,runner=runner)
            self.assertEqual(chosen,aligned)
            self.assertEqual(details["intensive_cross_reference"],"video_audio")
            self.assertEqual(details["intensive_agreement_thirds"],[1.,1.,1.])
            self.assertEqual(details["intensive_attempts"],8)

    def test_intensive_does_not_accept_conflicting_independent_reference(self):
        raw, aligned = fixture(lambda i: -2)
        _, wrong=fixture(lambda i: 9)
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d)
            def runner(cmd,**kwargs):
                reference=Path(cmd[1]).name
                Path(cmd[3]).write_bytes(wrong if reference.endswith(".en.srt") else aligned)
                return subprocess.CompletedProcess(cmd,0,b"",b"")
            with patch.object(alass,"available",return_value=True), \
                 patch.object(alass.gate,"STAGED",directory), \
                 patch.object(alass.gate,"subprocess_duration",return_value=1100), \
                 patch.object(alass.gate,"validate_srt",return_value={"cues":180}), \
                 patch.object(alass,"_embedded_english",return_value=None), \
                 patch.object(alass,"_intensive_external_english",return_value=b"possibly-wrong-reference"):
                with self.assertRaisesRegex(RuntimeError,"no_independent_reference"):
                    alass.intensive_align(directory/"video.mkv",raw,runner=runner)


    def test_direct_exact_stem_english_reference_without_legacy_import(self):
        raw,_=fixture(lambda i:0)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            video=root/"Episode S08E06.mkv"
            video.touch()
            good=root/"Episode S08E06.en.srt"
            good.write_bytes(raw)
            (root/"Other Episode.en.srt").write_bytes(raw)
            (root/"Episode S08E06.ja.srt").write_bytes(raw)
            link=root/"Episode S08E06.eng.srt"
            link.symlink_to(good)
            self.assertEqual(alass._intensive_external_english(video),raw)
            good.unlink()
            self.assertIsNone(alass._intensive_external_english(video))

    def test_no_independent_reference_skips_unverifiable_audio_trails(self):
        raw,_=fixture(lambda i:0)
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            calls=[]
            def runner(*a,**k):
                calls.append(a)
                raise AssertionError("ALASS must not run without an English reference")
            with patch.object(alass,"available",return_value=True), \
                 patch.object(alass.gate,"STAGED",folder), \
                 patch.object(alass.gate,"subprocess_duration",return_value=1100), \
                 patch.object(alass.gate,"validate_srt",return_value={"cues":180}), \
                 patch.object(alass,"_embedded_english",return_value=None), \
                 patch.object(alass,"_intensive_external_english",return_value=None):
                with self.assertRaisesRegex(RuntimeError,"missing_english_reference"):
                    alass.intensive_align(folder/"video.mkv",raw,runner=runner)
            self.assertEqual(calls,[])

    def test_constant_offset_supports_singular_alass_flag(self):
        raw,aligned=fixture(lambda i:-2)
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            flags=[]
            def runner(cmd,**kwargs):
                flags.append(cmd[-1])
                if cmd[-1]=="--no-splits":
                    return subprocess.CompletedProcess(cmd,2,b"",b"invalid option")
                Path(cmd[3]).write_bytes(aligned)
                return subprocess.CompletedProcess(cmd,0,b"",b"")
            with patch.object(alass,"available",return_value=True), \
                 patch.object(alass.gate,"STAGED",folder), \
                 patch.object(alass.gate,"subprocess_duration",return_value=1100), \
                 patch.object(alass.gate,"validate_srt",return_value={"cues":180}), \
                 patch.object(alass,"_embedded_english",return_value=None), \
                 patch.object(alass,"_intensive_external_english",return_value=b"en test"):
                chosen,_=alass.intensive_align(folder/"video.mkv",raw,runner=runner)
            self.assertEqual(chosen,aligned)
            self.assertIn("--no-split",flags)


    def test_jellyfin_indexed_english_read_only_exact_video(self):
        import io
        import json
        from tools import ja_first_catalog_manifest as cat
        raw,_=fixture(lambda i:0)
        jid="a"*32
        calls=[]
        video=Path("/tmp/Example S09E04.mkv")
        doc={"Id":jid,"Type":"Episode","Path":str(video),
             "MediaSources":[{"Id":"mediasrc-001",
             "MediaStreams":[{"Index":3,"Type":"Subtitle",
                              "Language":"eng","Codec":"subrip",
                              "IsExternal":True,"IsForced":False}]}]}
        def opener(req,timeout):
            calls.append(req.full_url)
            if req.full_url.endswith("MediaSources,MediaStreams"):
                return io.BytesIO(json.dumps(doc).encode())
            if req.full_url.endswith("Subtitles/3/Stream.srt"):
                return io.BytesIO(raw)
            raise AssertionError("Unapproved local Jellyfin endpoint")
        with patch.dict(sys.modules,{"ja_first_catalog_manifest":cat}), \
             patch.object(cat,"load_auth",return_value="test-only-auth"):
            result=alass._intensive_jellyfin_english(video,jid,opener=opener)
        self.assertEqual(result,raw)
        self.assertEqual(len(calls),2)
        self.assertTrue(all("127.0.0.1:8096" in url for url in calls))
        self.assertTrue(all("RemoteSearch" not in url for url in calls))
        doc["Path"]="/some/other/video.mkv"
        with patch.dict(sys.modules,{"ja_first_catalog_manifest":cat}), \
             patch.object(cat,"load_auth",return_value="test-only-auth"):
            self.assertIsNone(alass._intensive_jellyfin_english(video,jid,opener=opener))
        self.assertEqual(len(calls),3)

if __name__=="__main__":
    unittest.main()
