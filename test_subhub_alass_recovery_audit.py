"""Focused offline tests: held-only ALASS audit must not start a source job."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent / "tools"
sys.path.insert(0,str(TOOLS))
try:
    import subhub_alass_recovery_audit as audit
finally:
    sys.path.pop(0)


class HeldAuditTests(unittest.TestCase):
    def test_only_existing_held_non_anime_movies_are_candidates(self):
        def film(jid, status="ready_ja_search", folder="Horror",
                 kind="Movie", genres=()):
            return {"jellyfin_id":jid,"kind":kind,"status":status,
                    "host_path":str(Path("/mnt/2TB/Plex Expansion/Movies")/
                                    folder/"Film.mkv"),
                    "genres":list(genres),"title":"Film"}
        held="a"*32
        new="b"*32
        anime="c"*32
        covered="d"*32
        tv="e"*32
        rows=[film(held),film(new),film(anime,folder="Anime"),
              film(covered,status="existing_japanese_subtitle"),
              film(tv,kind="Episode")]
        stages=[(held,"1000","x"),(held,"2000","x"),
                (new,"3000","x"),(anime,"4000","x"),
                (covered,"5000","x"),(tv,"6000","x")]
        chosen=audit.candidates(rows,stages,{held,anime,covered,tv})
        self.assertEqual(list(chosen),[held])
        self.assertEqual(chosen[held][0],"1000")

    def test_held_ids_come_only_from_real_worker_receipts(self):
        valid="a"*32
        invalid="b"*32
        lines=[
            "BRUISER_PUBLISH_ITEM: "+json.dumps(
                {"jellyfin_id":valid,"result":"held"}),
            "BRUISER_PUBLISH_ITEM: "+json.dumps(
                {"jellyfin_id":invalid,"result":"published"}),
            "BRUISER_PUBLISH_ITEM: not-json",
            "HELD: "+"c"*32+" RuntimeError: fail",
        ]
        def runner(cmd,**kwargs):
            self.assertEqual(cmd[0],"journalctl")
            return subprocess.CompletedProcess(cmd,0,"\n".join(lines),"")
        self.assertEqual(audit.held_ids(runner=runner),{valid})

    def test_unknown_or_active_services_block_alignment(self):
        for state in ["activating","active","deactivating","unknown"]:
            def runner(cmd,**kwargs):
                return subprocess.CompletedProcess(cmd,0,state+"\n","")
            with self.subTest(state=state), self.assertRaisesRegex(
                RuntimeError,"another_subhub_job_active_or_unverifiable"):
                audit.require_idle(runner=runner)

    def test_inactive_services_allow_read_only_audit(self):
        checked=[]
        def runner(cmd,**kwargs):
            checked.append(cmd[-1])
            return subprocess.CompletedProcess(cmd,0,"inactive\n","")
        audit.require_idle(runner=runner)
        self.assertEqual(len(checked),len(audit.BUSY_UNITS))

    def test_stream_metadata_filters_english_text_not_forced_or_image(self):
        video=Path("/tmp/existing_video.mkv")
        streams=[
            {"codec_type":"subtitle","codec_name":"hdmv_pgs_subtitle",
             "tags":{"language":"eng"}},
            {"codec_type":"subtitle","codec_name":"subrip",
             "tags":{"language":"eng"},"disposition":{"forced":1}},
        ]
        def runner(cmd,**kwargs):
            return subprocess.CompletedProcess(cmd,0,
                                               json.dumps({"streams":streams}).encode(),b"")
        self.assertFalse(audit.embedded_en(video,runner=runner))
        streams.append({"codec_type":"subtitle","codec_name":"subrip",
                        "tags":{"language":"eng"},"disposition":{"forced":0}})
        self.assertTrue(audit.embedded_en(video,runner=runner))


if __name__=="__main__":
    unittest.main()
