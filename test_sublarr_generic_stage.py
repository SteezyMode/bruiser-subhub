"""Generic provider staging: evidence, no sidecars, trusted bytes, strict provenance."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools import ja_first_stage_sublarr as generic
from tools import ja_first_stage_timing_audit as timing


def movie():
    return {"jellyfin_id":"a"*32, "kind":"Movie",
            "status":"ready_ja_search","title":"Black Christmas","year":1974,
            "host_path":"/mnt/2TB/Plex Expansion/Movies/Horror/Black.Christmas.1974.mkv"}


def candidate(provider="subf2m",sid="abc-123"):
    return {"provider":provider,"subtitle_id":sid,"language":"ja",
            "filename":"Black.Christmas.1974.720p.Japanese.srt",
            "release_info":"Black.Christmas.1974.720p.WEB-DL",
            "kind":"full","forced":False,"format":"srt","score":85}


class GenericSublarrTests(unittest.TestCase):
    def test_generic_identity_and_providers_are_not_laundered(self):
        r=movie()
        self.assertTrue(generic.identity_ok(r,candidate()))
        self.assertTrue(generic.identity_ok(r,candidate("animetosho","id-456")))
        self.assertFalse(generic.identity_ok(r,candidate("opensubtitles")))
        self.assertFalse(generic.identity_ok(r,candidate("subdl")))
        other=dict(candidate(),forced=True)
        self.assertFalse(generic.identity_ok(r,other))
        wrong=dict(candidate(),filename="Black.Christmas.2006.720p.Japanese.srt",
                   release_info="Black.Christmas.2006.720p.WEB-DL")
        self.assertFalse(generic.identity_ok(r,wrong))
        english=dict(candidate(),language="en")
        self.assertFalse(generic.identity_ok(r,english))

    def test_episode_identity_requires_correct_series_and_episode(self):
        row={"jellyfin_id":"b"*32,"kind":"Episode","status":"ready_ja_search",
             "series_title":"Example Television","season":2,"episode":4,
             "host_path":"/mnt/2TB/Plex Expansion/Television/Example Television/S02E04.mkv"}
        c=dict(candidate(),filename="Example.Television.S02E04.Japanese.srt",
               release_info="Example.Television.S02E04.WEB-DL")
        self.assertTrue(generic.identity_ok(row,c))
        different=dict(c,filename="Example.Television.S02E05.Japanese.srt",
                       release_info="Example.Television.S02E05.WEB-DL")
        self.assertFalse(generic.identity_ok(row,different))
        different_series=dict(c,filename="Other.Television.S02E04.Japanese.srt",
                              release_info="Other.Television.S02E04.WEB-DL")
        self.assertFalse(generic.identity_ok(row,different_series))

    def test_provider_ids_are_origin_scoped(self):
        a,b=generic.remote_identity(candidate("subf2m","shared-555")), \
             generic.remote_identity(candidate("animetosho","shared-555"))
        self.assertNotEqual(a,b)
        self.assertEqual(generic.remote_identity(candidate()),generic.remote_identity(candidate()))

    def test_stage_regex_accepts_generic_without_accepting_arbitrary_prefix(self):
        jid="a"*32
        sid="1000000000001"
        self.assertIsNotNone(timing.STAGE_NAME.fullmatch(
            jid+".sublarr."+sid+".ja.srt"))
        self.assertIsNone(timing.STAGE_NAME.fullmatch(
            jid+".an-untrusted-provider."+sid+".ja.srt"))

    def test_worker_query_uses_only_title_identity_and_never_file_path(self):
        r=movie()
        with patch.object(generic.search,"query_for",return_value={
                "file_path":r["host_path"],"title":"Black Christmas",
                "year":1974,"language":"ja","imdb_id":"tt0071222"}):
            q=generic.worker_query(r)
        self.assertEqual(q,{"title":"Black Christmas","year":1974,
                            "imdb_id":"tt0071222"})
        self.assertNotIn("file_path",q)

    def test_download_receives_identity_and_bytes_never_printed(self):
        raw=b"1\n00:00:01,000 --> 00:00:02,000\n" + "日本語です".encode()
        result={"ok":True,"attempted":True,"length":len(raw),
                "sha256":hashlib.sha256(raw).hexdigest(),
                "content_b64":base64.b64encode(raw).decode()}
        call=SimpleNamespace(returncode=0,stdout=json.dumps(result),stderr="")
        with patch.object(generic.search,"query_for",return_value={
                "title":"Black Christmas","year":1974,"language":"ja"}), \
             patch.object(generic.ledger,"begin",return_value=1) as begin, \
             patch.object(generic.ledger,"finish") as finish:
            got=generic.provider_bytes(
                movie(),candidate(),
                runner=lambda *args,**kwargs:call)
        self.assertEqual(got,raw)
        begin.assert_called_once_with("subf2m","sublarr_provider_manager")
        finish.assert_called_once_with(1,"downloaded",byte_count=len(raw))

    def test_bad_hash_blocks_staging(self):
        raw=b"subtitle"
        fake={"ok":True,"attempted":False,"length":len(raw),
              "sha256":"0"*64,"content_b64":base64.b64encode(raw).decode()}
        with patch.object(generic.search,"query_for",return_value={
                "title":"Black Christmas","year":1974}):
            with self.assertRaisesRegex(RuntimeError,"bytes_integrity"):
                generic.provider_bytes(movie(),candidate(),
                    runner=lambda *args,**kwargs:SimpleNamespace(
                        returncode=0,stdout=json.dumps(fake),stderr=""))

    def test_download_specific_is_never_used(self):
        self.assertIn("get_provider_manager",generic.CONTAINER_WORKER)
        self.assertIn("manager.download(",generic.CONTAINER_WORKER)
        self.assertNotIn("save_subtitle(",generic.CONTAINER_WORKER)
        self.assertNotIn("download-specific",generic.CONTAINER_WORKER)

    def test_provenance_must_match_stored_candidate(self):
        r=movie()
        c=candidate()
        sid,_=generic.remote_identity(c)
        meta=generic.stage_metadata(r,c,b"valid",1200.0,{
            "cues":100,"japanese_characters":300,
            "japanese_cue_fraction":0.92})
        with patch.object(generic,"source_candidates",return_value=[c]):
            self.assertTrue(generic.validate_staged_provenance(r,r["jellyfin_id"],sid,meta))
            altered=dict(meta,source_remote_provider="animetosho")
            with self.assertRaisesRegex(RuntimeError,"not_verified"):
                generic.validate_staged_provenance(r,r["jellyfin_id"],sid,altered)
            altered=dict(meta,source_year=2006)
            with self.assertRaisesRegex(RuntimeError,"identity_changed"):
                generic.validate_staged_provenance(r,r["jellyfin_id"],sid,altered)

    def test_read_only_never_calls_provider_or_stage(self):
        r=movie()
        with patch.object(generic.stage,"read_inventory",
                          return_value={r["jellyfin_id"]:r}), \
             patch.object(generic,"source_candidates",return_value=[candidate()]), \
             patch.object(generic,"provider_bytes") as network, \
             patch.object(generic,"preserve") as write:
            generic.main(["--jellyfin-id",r["jellyfin_id"]])
            network.assert_not_called()
            write.assert_not_called()


if __name__=="__main__":
    unittest.main()
