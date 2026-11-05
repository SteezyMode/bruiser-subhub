"""Test exact endpoint contract, idempotency, no-translation and no overwrite."""
import unittest
from unittest.mock import patch

from tools import bruiser_ja_sublarr_rollout as flow


class FakeServer:
    def __init__(self, before=True):
        self.actions = []
        self.current = dict(flow.CONFIG)
        if before:
            self.current.update({
                "wanted_scan_interval_hours":0,
                "wanted_search_interval_hours":0,
                "auto_sync_after_download":False,
                "wanted_anime_only":True,
                "translation_enabled":True,
                "wanted_auto_translate":True,
                "wanted_skip_srt_on_no_ass":True,
                "upgrade_enabled":True,
            })
        self.folders = [
            dict(id=i,path=path,enabled=i<3,outside_media_path=False)
            for i,path in sorted(flow.EXPECTED.items())]

    def __call__(self,path,payload=None,method=None):
        self.actions.append((method or "GET",path,payload))
        if path=="/api/v1/providers/health":
            return {"providers":[{"name":"opensubtitles","gate":"ok",
                                  "initialized":True,"healthy":True}]}
        if path=="/api/v1/sync/engines":
            return {"engines":[{"name":"ffsubsync","available":True}]}
        if path=="/api/v1/standalone/folders" and method is None:
            return [dict(x) for x in self.folders]
        if path=="/api/v1/config" and method is None:
            return dict(self.current)
        if path=="/api/v1/config" and method=="PUT":
            self.current.update(payload)
            return {"status":"saved","updated_keys":list(payload),"config":dict(self.current)}
        if path.startswith("/api/v1/standalone/folders/") and method=="PUT":
            i=int(path.rsplit("/",1)[-1])
            row=next(x for x in self.folders if x["id"]==i)
            row.update(payload)
            return dict(row)
        if path=="/api/v1/standalone/scan" and method=="POST":
            return {"message":"Scan started"}
        raise AssertionError((path,payload,method))


class TestRollout(unittest.TestCase):
    def test_policy_disables_translation_upgrades_and_sync_holds_large_offsets(self):
        c=flow.CONFIG
        self.assertIs(c["wanted_auto_translate"],False)
        self.assertIs(c["translation_enabled"],False)
        self.assertIs(c["upgrade_enabled"],False)
        self.assertIs(c["subtitle_health_auto_fix"],False)
        self.assertIs(c["auto_sync_after_download"],True)
        self.assertEqual(c["auto_sync_engine"],"ffsubsync")
        self.assertLessEqual(c["sync_sanity_threshold_ms"],30000)
        self.assertLessEqual(c["wanted_search_max_items_per_run"],40)

    def test_plan_only_does_not_mutate_server(self):
        srv=FakeServer()
        with patch.object(flow,"folder_plan",return_value=[3,4,5,6]),\
             patch.object(flow,"exact_movie_files",return_value=["/media/bigdisk-video/Movies/You Were Never Really Here.mkv"]):
            r=flow.run(apply=False,requester=srv)
        self.assertEqual(r["folders"],[3,4,5,6])
        self.assertFalse(any(m in ("PUT","POST") for m,p,b in srv.actions))

    def test_apply_protects_config_before_enabling_and_scan(self):
        srv=FakeServer()
        with patch.object(flow,"folder_plan",side_effect=[[3,4,5,6],[]]),\
             patch.object(flow,"exact_movie_files",return_value=[]):
            flow.run(apply=True,requester=srv)
        writes=[(m,p) for m,p,_ in srv.actions if m in ("PUT","POST")]
        self.assertEqual(writes[0],("PUT","/api/v1/config"))
        self.assertEqual(writes[-1],("POST","/api/v1/standalone/scan"))
        self.assertEqual(sum(p.startswith("/api/v1/standalone/folders/") for m,p in writes),4)
        self.assertEqual(srv.current["wanted_auto_translate"],False)
        self.assertEqual(srv.current["upgrade_enabled"],False)

    def test_no_write_when_provider_not_healthy(self):
        srv=FakeServer()
        def bad(path,payload=None,method=None):
            if path=="/api/v1/providers/health":
                return {"providers":[{"name":"opensubtitles","gate":"no_pool_key",
                                      "healthy":True,"initialized":True}]}
            return srv(path,payload,method)
        with self.assertRaisesRegex(RuntimeError,"provider"):
            flow.run(apply=True,requester=bad)
        self.assertFalse(any(m in ("PUT","POST") for m,p,b in srv.actions))

    def test_folder_roots_must_match_exact_expected(self):
        folders=[dict(id=i,path=p,enabled=True,outside_media_path=False)
                 for i,p in flow.EXPECTED.items()]
        folders[4]["path"]="/media/unknown"
        with self.assertRaisesRegex(RuntimeError,"path changed"):
            flow.folder_plan(folders,isdir=lambda x:True)

    def test_idempotent_plan_after_activation(self):
        srv=FakeServer(before=False)
        for f in srv.folders: f["enabled"]=True
        with patch.object(flow,"folder_plan",return_value=[]),\
             patch.object(flow,"exact_movie_files",return_value=[]):
            result=flow.run(apply=False,requester=srv)
        self.assertEqual(result["config"],{})
        self.assertEqual(result["folders"],[])


if __name__=="__main__":
    unittest.main()
