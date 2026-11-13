"""A Sublarr process launched by docker exec must have DB-aware Flask context.

Pure offline worker execution with stubbed Flask/provider packages. No Sublarr,
provider HTTP, database, video, provider quotas or filesystem writes.
"""
from contextlib import contextmanager
import io
import json
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from tools import ja_first_stage_sublarr as generic


def module(name, **attrs):
    m=ModuleType(name)
    for key,value in attrs.items():
        setattr(m,key,value)
    return m


class ContextTests(unittest.TestCase):
    def test_probe_creates_minimal_db_flask_context_with_ui_overrides(self):
        state={"in_context":False,"db_uri":None,"reloaded":False,
               "manager_seen":False,"created":0}
        class FakeApp:
            def __init__(self,name,static_folder=None):
                self.config={}
                state["created"]+=1
            @contextmanager
            def app_context(self):
                state["in_context"]=True
                try:
                    yield
                finally:
                    state["in_context"]=False
        class FakeDb:
            def init_app(self,app):
                state["db_uri"]=app.config["SQLALCHEMY_DATABASE_URI"]
        def fetch_config():
            assert state["in_context"]
            return {"providers_enabled":"subf2m"}
        def reload_settings(values):
            assert state["in_context"]
            assert values["providers_enabled"]=="subf2m"
            state["reloaded"]=True
        def get_manager():
            assert state["in_context"]
            assert state["reloaded"]
            state["manager_seen"]=True
            return SimpleNamespace(_providers={"subf2m":object(),"subdl":object()})
        config=module("config",get_settings=lambda:SimpleNamespace(
            get_database_url=lambda:"sqlite:////config/sublarr.db",database_url=""),
            reload_settings=reload_settings)
        db=module("db")
        db.__path__=[]
        db_config=module("db.config",get_all_config_entries=fetch_config)
        providers=module("providers",get_provider_manager=get_manager)
        providers.__path__=[]
        base=module("providers.base",VideoQuery=lambda **kwargs:kwargs)
        modules={"flask":module("flask",Flask=FakeApp),
                 "config":config,"extensions":module("extensions",db=FakeDb()),
                 "db":db,"db.config":db_config,
                 "providers":providers,"providers.base":base}
        dest=io.StringIO()
        with patch.dict(sys.modules,modules), \
             patch.object(sys,"stdin",io.StringIO('{"mode":"probe"}')), \
             patch.object(sys,"stdout",dest):
            exec(generic.CONTAINER_WORKER,{"__name__":"__main__"})
        answer=json.loads(dest.getvalue())
        self.assertEqual(answer["active_provider_count"],2)
        self.assertTrue(answer["subf2m_enabled"])
        self.assertFalse(answer["attempted"])
        self.assertEqual(state["created"],1)
        self.assertTrue(state["manager_seen"])
        self.assertFalse(state["in_context"])
        self.assertEqual(state["db_uri"],"sqlite:////config/sublarr.db")
        self.assertNotIn("app import",generic.CONTAINER_WORKER)
        self.assertNotIn("=create_app(",generic.CONTAINER_WORKER)

    def test_probe_cli_is_read_only_and_errors_cleanly(self):
        fake=SimpleNamespace(returncode=0,stdout=json.dumps({
            "ok":True,"attempted":False,"active_provider_count":18,
            "subf2m_enabled":True}),stderr="")
        with patch("builtins.print") as printout:
            generic.probe_manager(runner=lambda *a,**k:fake)
        self.assertTrue(any("PASS" in str(call.args) for call in printout.call_args_list))
        bad=SimpleNamespace(returncode=0,stdout=json.dumps({
            "ok":False,"reason":"RuntimeError","attempted":False}),stderr="")
        with self.assertRaisesRegex(RuntimeError,"sublarr_probe_RuntimeError"):
            generic.probe_manager(runner=lambda *a,**k:bad)
        with self.assertRaises(SystemExit):
            generic.main(["--probe-manager","--apply"])


if __name__=="__main__":
    unittest.main()
