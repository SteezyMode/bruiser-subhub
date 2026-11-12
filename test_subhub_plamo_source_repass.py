"""Historical PLaMO cohort re-pass: exact saved releases, bounded, no AI."""
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch

from tools import subhub_plamo_source_repass as repass


def movie(jid="a"*32,title="Green Room",year=2016,host_path="/tmp/film.mkv"):
    return {"jellyfin_id":jid,"kind":"Movie","status":"ready_ja_search",
            "title":title,"year":year,"host_path":host_path}


class SourceOnlyRepassTests(unittest.TestCase):
    def test_saved_releases_only_pass_exact_provider_identity(self):
        row=movie()
        doc={"results":{"candidates":[
            {"provider":"opensubtitles","subtitle_id":"4247924",
             "language":"ja","filename":"Green.Room.2015.BluRay.ja",
             "grade":"review"},
            {"provider":"opensubtitles","subtitle_id":"1001",
             "language":"ja","filename":"Wrong.Movie.2015.ja"},
            {"provider":"subdl","subtitle_id":"release_1","language":"ja",
             "filename":"Green.Room.2015.1080p.ja.srt"},
            {"provider":"animetosho","subtitle_id":"other"},
        ]}}
        oa=SimpleNamespace(
            identity_ok=Mock(side_effect=lambda row,c:
                             "Green.Room" in str(c.get("filename"))),
            known_rejected_download=Mock(return_value=False))
        da=SimpleNamespace(
            identity_ok=Mock(return_value=True),
            numeric_id=Mock(return_value=("90012345","digest")))
        found=repass.eligible_saved(row,doc,set(),set(),
                                   opensub=oa,subdl_adapter=da)
        self.assertEqual({c["provider"] for c in found},{"opensubtitles","subdl"})
        self.assertEqual(len(found),2)
        oa.known_rejected_download.assert_called_once()

    def test_saved_staged_and_duration_held_are_not_downloaded_twice(self):
        row=movie()
        doc={"results":{"candidates":[
            {"provider":"opensubtitles","subtitle_id":"4247924",
             "language":"ja","filename":"Green.Room.2015.ja"},
            {"provider":"subdl","subtitle_id":"r1234","language":"ja",
             "filename":"Green.Room.2015.ja.srt"},
        ]}}
        oa=SimpleNamespace(
            identity_ok=Mock(return_value=True),
            known_rejected_download=Mock(return_value=False))
        da=SimpleNamespace(
            identity_ok=Mock(return_value=True),
            numeric_id=Mock(return_value=("9999999","digest")))
        found=repass.eligible_saved(
            row,doc,{(row["jellyfin_id"],"4247924")},
            {(row["jellyfin_id"],"9999999")},
            opensub=oa,subdl_adapter=da)
        self.assertEqual(found,[])
        oa.known_rejected_download.assert_not_called()

    def test_readonly_pass_does_not_start_download_publication_or_model(self):
        jid="b"*32
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"test.mkv"
            p.write_bytes(b"video")
            item=movie(jid=jid,host_path=str(p))
            report={"items":[{"jellyfin_id":jid}],
                    "recorded_plamo_pending":1,
                    "journal_complete_for_queue":True}
            c={"results":{"candidates":[]}}
            with patch.object(repass,"historical_cohort",
                              return_value=(report,{jid:item},{jid:c},{})), \
                 patch.object(repass.stage,"read_staged",return_value=set()), \
                 patch.object(repass.stage,"rejected_duration_candidates",
                              return_value=set()), \
                 patch.object(repass.stage,"japanese_sidecar_exists",
                              return_value=False), \
                 patch.object(repass,"_publisher") as publish, \
                 patch.object(repass,"_acquire") as acquire, \
                 patch.object(repass,"_safe_apply") as gate:
                repass.repass(apply=False)
            publish.assert_not_called()
            acquire.assert_not_called()
            gate.assert_not_called()

    def test_one_provider_budget_stops_all_further_gets(self):
        ids=["b"*32,"c"*32]
        with tempfile.TemporaryDirectory() as d:
            paths=[]
            rows={}
            for jid in ids:
                p=Path(d)/(jid+".mkv")
                p.write_bytes(b"video")
                paths.append(p)
                rows[jid]=movie(jid=jid,host_path=str(p))
            doc=lambda:{"results":{"candidates":[
                {"provider":"opensubtitles","subtitle_id":"4247924",
                 "filename":"Green.Room.2015.ja","language":"ja"}]}}
            report={"items":[{"jellyfin_id":jid} for jid in ids],
                    "recorded_plamo_pending":2,
                    "journal_complete_for_queue":True}
            with patch.object(repass,"historical_cohort",
                              return_value=(report,rows,
                                            {jid:doc() for jid in ids},{})), \
                 patch.object(repass.stage,"read_staged",return_value=set()), \
                 patch.object(repass.stage,"rejected_duration_candidates",
                              return_value=set()), \
                 patch.object(repass.stage,"japanese_sidecar_exists",
                              return_value=False), \
                 patch.object(repass.stage,"identity_ok",return_value=True), \
                 patch.object(repass.stage,"known_rejected_download",
                              return_value=False), \
                 patch.object(repass,"_safe_apply"), \
                 patch.object(repass,"_acquire",
                              return_value=(0,False)) as acquire, \
                 patch.object(repass,"_publisher") as publish:
                repass.repass(apply=True,stage_budget=1,
                              publish_attempt_budget=3)
            acquire.assert_called_once()
            publish.assert_not_called()


if __name__=="__main__":
    unittest.main()
